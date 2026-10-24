#!/usr/bin/env python3
"""Caller-arena thread contracts. --cross checks Windows/macOS links only.

Native execution requires a supported 64-bit Linux, Windows, or macOS host.
Foreign targets are never executed; no native OS-failure injection is attempted.
Every compiler and child process has a timeout, including gated worker failures.
"""
import argparse
import os
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build' /
                          ('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve())
IMPORTS = '''use "std/thread" thread
use "std/mem" mem
use "std/sync" sync
use "std/errors" errors
'''
SOURCE = IMPORTS + r'''
struct Shared { gate: sync.AtomicU32, arrived: sync.AtomicU32, value: u32 }
fn worker(context: rawptr) isize {
  shared := #cast(*Shared, context)
  sync.store_u32(&shared.arrived, 1)
  for sync.load_u32(&shared.gate) == 0 { _ = thread.yield_now() }
  shared.value = 42
  return 0
}
fn invalid(result: thread.SpawnResult, arena: *mem.Arena, mark: usize) {
  if result.ok || result.value != nil || result.error != 0 || result.kind != errors.Kind.InvalidInput || mem.arena_mark(arena) != mark {
    #panic("invalid input result/rollback")
  }
}
fn joined(value: *thread.Thread) {
  result := thread.join(value)
  if !result.ok || result.kind != errors.Kind.None || result.error != 0 || result.value != 0 || thread.id(value) != 0 { #panic("join result") }
}
fn main() {
  zero := thread.SpawnResult{}
  if zero.ok || zero.value != nil || zero.kind != errors.Kind.None || zero.error != 0 { #panic("zero spawn result") }
  result := thread.Result{}
  if result.ok || result.value != 0 || result.kind != errors.Kind.None || result.error != 0 { #panic("zero result") }
  empty := thread.Thread{}
  if thread.id(&empty) != 0 { #panic("zero id") }
  joined(&empty)
  joined(&empty)
  storage: [4096]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  _ = mem.push_bytes_uninit(&arena, 7)
  mark := mem.arena_mark(&arena)
  stack: [131072]u8 = []
  for size in [0, 1, 255] {
    invalid(thread.spawn_with_size(&arena, #cast(usize, size), worker, nil), &arena, mark)
    invalid(thread.spawn(&arena, stack[..size], worker, nil), &arena, mark)
  }
  invalid(thread.spawn_with_size(&arena, 131072, nil, nil), &arena, mark)
  invalid(thread.spawn(&arena, stack[..], nil, nil), &arena, mark)
  first := Shared{}
  second := Shared{}
  owned := thread.spawn_with_size(&arena, 131072, worker, #cast(rawptr, &first))
  if !owned.ok || owned.value == nil || owned.kind != errors.Kind.None || owned.error != 0 { #panic("owned spawn") }
  stable := owned.value
  owned_mark := mem.arena_mark(&arena)
  borrowed := thread.spawn(&arena, stack[..], worker, #cast(rawptr, &second))
  if !borrowed.ok || borrowed.value == nil || borrowed.kind != errors.Kind.None || borrowed.error != 0 { #panic("borrowed spawn") }
  if borrowed.value == stable || owned.value != stable || owned_mark <= mark { #panic("stable distinct nodes") }
  for sync.load_u32(&first.arrived) == 0 || sync.load_u32(&second.arrived) == 0 { _ = thread.yield_now() }
  if thread.id(stable) == 0 || thread.id(borrowed.value) == 0 || thread.id(stable) == thread.id(borrowed.value) { #panic("two active ids") }
  base := #cast(usize, &storage[0])
  end := base + #len(storage)
  first_address := #cast(usize, stable)
  second_address := #cast(usize, borrowed.value)
  if first_address < base || first_address >= end || second_address < base || second_address >= end { #panic("nodes outside caller arena") }
  nodes := mem.arena_mark(&arena)
  if nodes <= owned_mark { #panic("second node allocation") }
  // A later arena allocation must neither move nor overwrite either descriptor.
  tail := mem.push_bytes_uninit(&arena, 64)
  for *byte in tail { byte.* = 99 }
  retained := mem.arena_mark(&arena)
  sync.store_u32(&first.gate, 1)
  sync.store_u32(&second.gate, 1)
  joined(stable)
  joined(borrowed.value)
  if first.value != 42 || second.value != 42 { #panic("join visibility") }
  joined(stable)
  joined(borrowed.value)
  if mem.arena_mark(&arena) != retained { #panic("join released caller nodes") }
  for byte in tail { if byte != 99 { #panic("join changed caller allocation") } }
  // Borrowed storage remains usable after join, even on hosts owning OS stacks.
  stack[0] = 77
  if stack[0] != 77 || owned.value != stable { #panic("borrowed stack lifetime") }
}
'''
EXHAUSTION = IMPORTS + r'''
fn forbidden(context: rawptr) isize { if context == nil { #panic("WORKER_STARTED") }
return 0 }
fn main() {
  backing: [1]u8 = []
  arena := mem.arena_from_buffer(backing[..0])
  stack: [131072]u8 = []
  SPAWN
  #panic("SPAWN_RETURNED")
}
'''


def build(work, source, mode, target=None):
    (work / 'main.dyn').write_text(source)
    output = work / ('probe.exe' if target == 'x86_64-windows' or os.name == 'nt' else 'probe')
    command = [DYN, 'build', str(work), '--' + mode, '--quiet', '--no-cache', '--output', str(output)]
    if target:
        command += ['--target', target]
    subprocess.run(command, check=True, timeout=120)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cross', action='store_true', help='also cross-link Windows x64 and macOS arm64; requires their runtime/link tools')
    args = parser.parse_args()
    if platform.system() not in ('Linux', 'Windows', 'Darwin') or platform.machine().lower() not in ('x86_64', 'amd64', 'aarch64', 'arm64'):
        raise SystemExit('SKIP: requires a supported 64-bit native thread host')
    with tempfile.TemporaryDirectory(prefix='dyn-thread-results-') as temporary:
        work = Path(temporary)
        for mode in ('debug', 'release'):
            output = build(work, SOURCE, mode)
            result = subprocess.run([str(output)], capture_output=True, timeout=20)
            assert result.returncode == 0, (mode, result.stdout, result.stderr)
            for call in ('thread.spawn_with_size(&arena, 131072, forbidden, nil)',
                         'thread.spawn(&arena, stack[..], forbidden, nil)'):
                output = build(work, EXHAUSTION.replace('SPAWN\n', '_ = ' + call + '\n'), mode)
                result = subprocess.run([str(output)], capture_output=True, timeout=10)
                diagnostic = result.stdout + result.stderr
                assert result.returncode != 0 and b'arena exhausted' in diagnostic, (mode, diagnostic)
                assert b'WORKER_STARTED' not in diagnostic and b'SPAWN_RETURNED' not in diagnostic, diagnostic
            print('PASS native thread results and arena exhaustion ' + mode, flush=True)
            if args.cross:
                for target in ('x86_64-windows', 'aarch64-macos'):
                    for source in (SOURCE, EXHAUSTION.replace('SPAWN\n', '_ = thread.spawn_with_size(&arena, 131072, forbidden, nil)\n')):
                        build(work, source, mode, target)
                    print('PASS target link ' + target + ' ' + mode + ' (execution requires native host)', flush=True)


if __name__ == '__main__':
    main()
