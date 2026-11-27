#!/usr/bin/env python3
"""Copied arena core: growth through mocked OS mappings, and the panics when
the OS refuses a mapping or a commit.

Mappings are deterministic in-process buffers, not real OS failures.
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
fn mapping_sparse(bytes: []u8) { _ = bytes }
fn mapping_protect(bytes: []u8, from: usize, to: usize, accessible: bool) bool { _ = bytes
 _ = from
 _ = to
 _ = accessible
 return true }
fn mapping_thread_id() u64 { return 0 }
fn mapping_check_lifetimes() bool { return false }
fn mapping_release(bytes: []u8) isize { mock_releases += 1
 return 0 }
'''
SOURCE = r'''use mem "./model"
fn require(ok: bool) { if !ok { #panic("arena native contract") } }
fn bounded() *mem.Arena {
 source := mem.pages(4096)
 source.block_size = 160
 return mem.arena_from_source(source)
}
fn growth() {
 arena := bounded()
 defer mem.arena_release(arena)
 prefix := mem.push_bytes(arena, 16)
 for i in 0..16 { prefix[i] = #cast(u8, i + 17) }
 calls := mem.allocation_calls()
 grown := mem.push<u8>(arena)
 require(mem.allocation_calls() == calls + 1 && grown.* == 0 && arena.current != arena)
 for i in 0..16 { require(prefix[i] == #cast(u8, i + 17)) }
 releases := mem.release_calls()
 mem.arena_reset(arena)
 require(mem.release_calls() == releases + 1 && arena.current == arena)
}
fn native_failure() {
 arena := bounded()
 _ = mem.push_bytes(arena, 16)
 mem.inject_failure(-123)
 _ = mem.push<u8>(arena)
}
fn commitment_failure() {
 arena := bounded()
 _ = mem.push_bytes(arena, 16)
 mem.inject_commit_failure()
 _ = mem.push<u8>(arena)
}
fn payload_commitment_failure() {
 source := mem.pages(512)
 source.block_size = 512
 arena := mem.arena_from_source(source)
 _ = mem.push_bytes(arena, 8)
 arena.current.committed = mem.ArenaHeader
 mem.inject_commit_failure()
 _ = mem.push_bytes(arena, 8)
}
fn main() {
 CASE()
}
'''
# Each case and what it must print; an empty message means a clean exit.
CASES = [
    ('growth', ''),
    ('native_failure', 'cannot reserve arena memory'),
    ('commitment_failure', 'cannot reserve arena memory'),
    ('payload_commitment_failure', 'cannot commit arena memory'),
]

with tempfile.TemporaryDirectory(prefix='dyn-arena-native-errors-') as temporary:
    work = Path(temporary)
    model = work / 'model'
    model.mkdir()
    (model / 'mem.dyn').write_text((ROOT / 'std/mem/mem.dyn').read_text())
    (model / 'sizes.dyn').write_text((ROOT / 'std/mem/sizes.dyn').read_text())
    (model / 'mapping.dyn').write_text(MOCK)
    for case, message in CASES:
        (work / 'main.dyn').write_text(SOURCE.replace('CASE', case))
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
                result = subprocess.run([str(output)], env=env, capture_output=True, text=True, timeout=15)
                if message:
                    assert result.returncode == 101 and message in result.stderr, (case, mode, result.returncode, result.stderr)
                else:
                    assert result.returncode == 0, (case, mode, result.returncode, result.stderr)
                print(f'PASS arena native {case} {mode} {"tree" if tree else "SSA"}', flush=True)
    (work / 'main.dyn').write_text(SOURCE.replace('CASE', 'growth'))

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
            print(f'PASS arena native growth {target} {mode}', flush=True)
