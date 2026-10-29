#!/usr/bin/env python3
"""Copied arena core: native growth diagnostics and transactional failure state.

Mappings are deterministic in-process buffers, not real OS failures. A failed
header commitment reports the current synthetic -12 mapping code; this test does
not claim preservation of a real Windows GetLastError value for commitment.
"""
import os
import shlex
import shutil
import signal
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
MOCK = r'''
const DefaultBlock: usize = 160
mock_storage: [16][8208]u8
mock_slot: usize
mock_calls: usize
mock_releases: usize
mock_fail: bool
mock_code: isize
mock_uncommitted: bool
mock_commit_fail: bool
pub fn inject_failure(code: isize) { mock_fail = true
 mock_code = code }
pub fn inject_commit_failure() { mock_uncommitted = true
 mock_commit_fail = true }
pub fn clear_failure() { mock_fail = false
 mock_uncommitted = false
 mock_commit_fail = false }
pub fn allocation_calls() usize { return mock_calls }
pub fn release_calls() usize { return mock_releases }
fn mapping_allocate(size: usize) Mapping {
 mock_calls += 1
 if mock_fail { return Mapping{error: mock_code} }
 if size > 8192 || mock_slot >= 16 { #panic("mock storage exhausted") }
 bytes := mock_storage[mock_slot][..]
 mock_slot += 1
 skip := (16 - (#cast(usize, &bytes[0]) & 15)) & 15
 committed := size
 if mock_uncommitted { committed = 0 }
 return Mapping{bytes: bytes[skip..skip+size], committed: committed, ok: true}
}
fn mapping_commit(bytes: []u8, from: usize, to: usize) bool {
 return !mock_commit_fail
}
fn mapping_release(bytes: []u8) isize { mock_releases += 1
 return 0 }
'''
SOURCE = r'''use "./model" mem
fn require(ok: bool) { if !ok { #panic("arena native error contract") } }
fn unchanged(arena: *mem.Arena, before: mem.ArenaSnapshot, mark: usize,
 backing: usize, current: *mem.Arena, prefix: []const u8) {
 after := mem.arena_snapshot(arena)
 require(mem.arena_mark(arena) == mark && arena.backing == backing && arena.current == current)
 require(after.blocks == before.blocks && after.used == before.used && after.capacity == before.capacity)
 require(after.remaining == before.remaining && after.peak_used == before.peak_used)
 require(after.allocation_failures == before.allocation_failures + 1)
 for i in 0..#len(prefix) { require(prefix[i] == #cast(u8, i + 17)) }
}
fn native_failure(code: isize) {
 arena := mem.arena_create_bounded(160, 4096)
 defer mem.arena_release(arena)
 prefix := mem.push_bytes_uninit(arena, 16)
 for i in 0..16 { prefix[i] = #cast(u8, i + 17) }
 before := mem.arena_snapshot(arena)
 mark := mem.arena_mark(arena)
 backing := arena.backing
 current := arena.current
 calls := mem.allocation_calls()
 releases := mem.release_calls()
 mem.inject_failure(code)
 result := mem.arena_try_push(arena, 1, 1)
 require(!result.ok && result.error == mem.ErrorKind.System && result.code == code)
 require(result.memory == nil && result.size == 0)
 require(mem.allocation_calls() == calls + 1 && mem.release_calls() == releases)
 unchanged(arena, before, mark, backing, current, prefix)
 mem.clear_failure()
 retry := mem.arena_try_push(arena, 1, 1)
 require(retry.ok && retry.error == mem.ErrorKind.None && retry.code == 0)
 require(mem.arena_snapshot(arena).blocks == 2 && retry.memory.* == 0)
 for i in 0..16 { require(prefix[i] == #cast(u8, i + 17)) }
}
fn local_failures() {
 arena := mem.arena_create_bounded(160, 160)
 defer mem.arena_release(arena)
 _ = mem.push_bytes_uninit(arena, 16)
 calls := mem.allocation_calls()
 mark := mem.arena_mark(arena)
 capacity := mem.arena_try_push(arena, 1, 1)
 require(!capacity.ok && capacity.error == mem.ErrorKind.Capacity && capacity.code == 0)
 overflow := mem.arena_try_push(arena, ~#cast(usize, 0), 1)
 require(!overflow.ok && overflow.error == mem.ErrorKind.Overflow && overflow.code == 0)
 alignment := mem.arena_try_push(arena, 1, 3)
 require(!alignment.ok && alignment.error == mem.ErrorKind.InvalidAlignment && alignment.code == 0)
 require(mem.allocation_calls() == calls && mem.arena_mark(arena) == mark)
 require(mem.arena_snapshot(arena).allocation_failures == 3)
}
fn commitment_failure() {
 arena := mem.arena_create_bounded(160, 4096)
 defer mem.arena_release(arena)
 prefix := mem.push_bytes_uninit(arena, 16)
 for i in 0..16 { prefix[i] = #cast(u8, i + 17) }
 before := mem.arena_snapshot(arena)
 mark := mem.arena_mark(arena)
 backing := arena.backing
 current := arena.current
 calls := mem.allocation_calls()
 releases := mem.release_calls()
 mem.inject_commit_failure()
 result := mem.arena_try_push(arena, 1, 1)
 // mapping_commit is boolean; -12 is synthetic, not an actual Win32 code.
 require(!result.ok && result.error == mem.ErrorKind.System && result.code == -12)
 require(mem.allocation_calls() == calls + 1 && mem.release_calls() == releases + 1)
 unchanged(arena, before, mark, backing, current, prefix)
 mem.clear_failure()
 retry := mem.arena_try_push(arena, 1, 1)
 require(retry.ok && retry.code == 0)
}
fn payload_commitment_failure() {
 arena := mem.arena_create_bounded(512, 512)
 defer mem.arena_release(arena)
 bytes := mem.arena_push(arena, 8, 1)
 bytes.* = 91
 arena.current.committed = mem.ArenaHeader
 mark := mem.arena_mark(arena)
 mem.inject_commit_failure()
 failed := mem.arena_try_push_uninit(arena, 8, 1)
 require(!failed.ok && failed.error == mem.ErrorKind.System && failed.code == -12)
 require(mem.arena_mark(arena) == mark && bytes.* == 91)
 require(!mem.arena_try_extend(arena, bytes, 8, 8))
 require(mem.arena_mark(arena) == mark && bytes.* == 91)
 mem.clear_failure()
 require(mem.arena_try_push_uninit(arena, 8, 1).ok)
}
fn main() {
 payload_commitment_failure()
 native_failure(-123)
 native_failure(0)
 local_failures()
 commitment_failure()
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-arena-native-errors-') as temporary:
    work = Path(temporary)
    model = work / 'model'
    model.mkdir()
    (model / 'mem.dyn').write_text((ROOT / 'std/mem/mem.dyn').read_text())
    (model / 'sizes.dyn').write_text((ROOT / 'std/mem/sizes.dyn').read_text())
    (model / 'mapping.dyn').write_text(MOCK)
    (work / 'main.dyn').write_text(SOURCE)
    for mode in ('debug', 'release'):
        for tree in (False, True):
            env = dict(os.environ, DYN_SDK=str(ROOT))
            if tree:
                env['DYN_NO_SSA'] = '1'
            else:
                env.pop('DYN_NO_SSA', None)
            output = work / 'run'
            subprocess.run([DYN, 'build', str(work), '--' + mode, '--no-cache', '--quiet',
                            '--output', str(output)], env=env, check=True, timeout=120)
            subprocess.run([str(output)], env=env, check=True, capture_output=True, timeout=15)
            print(f'PASS arena native errors {mode} {"tree" if tree else "SSA"}: -123/zero, state/counters, local failures, synthetic header commitment code', flush=True)

    targets = [
        ('riscv32-none-soft', 'DYN_QEMU_RISCV32', 'qemu-system-riscv32',
         ['-machine', 'virt', '-bios', 'none', '-cpu', 'sifive-e31']),
        ('thumbv7em-none-soft', 'DYN_QEMU_ARM', 'qemu-system-arm',
         ['-machine', 'mps2-an500', '-semihosting-config', 'enable=on,target=native']),
    ]
    for target, variable, program, board in targets:
        configured = shlex.split(os.environ.get(variable, ''))
        discovered = shutil.which(program)
        fallback = Path('/tmp/dyn-qemu') / program
        qemu = configured or ([discovered] if discovered else ([str(fallback)] if fallback.is_file() else []))
        if not qemu or not shutil.which(qemu[0]):
            print(f'SKIP arena native errors {target}: missing {variable}/{program}', flush=True)
            continue
        env = dict(os.environ, DYN_SDK=str(ROOT))
        env.pop('DYN_NO_SSA', None)
        for mode in ('debug', 'release'):
            image = work / (target + '-' + mode)
            subprocess.run([DYN, 'build', str(work), '--target', target, '--' + mode,
                            '--no-cache', '--quiet', '--output', str(image)],
                           env=env, check=True, timeout=120)
            process = subprocess.Popen([*qemu, *board, '-nographic', '-kernel', str(image)],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                output, _ = process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=5)
                raise AssertionError(f'arena native errors guest timed out: {target} {mode}')
            assert process.returncode == 0 and output == b'', (target, mode, process.returncode, output[:65536])
            print(f'PASS arena native errors {target} {mode}: private Growth return ABI and exact diagnostics', flush=True)
