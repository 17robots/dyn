#!/usr/bin/env python3
"""Arena byte zeroing contracts across alignment, dirty reuse and word widths."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/mem"
use "std/io"
struct Padded { a: u8, b: usize, c: u8 }
fn expect(ok: bool) { if !ok { #panic("arena zero contract") } }
fn fill(bytes: []u8) { for *b in bytes { b.* = 171 } }
// Header fields are live mutable metadata; dirty only bytes outside that region.
fn fill_payload(bytes: []u8, arena: *mem.Arena) {
  header := #cast(usize,arena)-#cast(usize,&bytes[0])
  for i in 0..bytes.len {
    if i < header || i-header >= mem.ArenaHeader { bytes[i]=171 }
  }
}
fn verify(bytes: []u8, arena: *mem.Arena, start: usize, size: usize) {
  header := #cast(usize,arena)-#cast(usize,&bytes[0])
  for i in 0..bytes.len {
    if i >= header && i-header < mem.ArenaHeader { continue }
    if i >= start && i-start < size { expect(bytes[i] == 0) }
    else { expect(bytes[i] == 171) }
  }
}
// count zeroed values of T in a dirty caller buffer at offset: aligned,
// zeroed, nothing around them touched, and zeroed again after a poisoned reset.
fn typed_array<T>(count:usize, offset:usize) {
  backing:[1400]u8
  fill(backing[..])
  arena:=mem.arena_from_buffer(backing[offset..1300])
  values:=mem.push_array<T>(arena, count)
  expect(values.len==count)
  if count==0 {
    expect(arena.offset==mem.ArenaHeader)
    verify(backing[..],arena,0,0)
    return
  }
  start:=#cast(usize,&values[0])-#cast(usize,&backing[0])
  expect((#cast(usize,&values[0]) & (#alignof(T)-1))==0)
  base:=#cast(usize,arena)-#cast(usize,&backing[0])
  expect(arena.offset==start-base+count*#sizeof(T))
  verify(backing[..],arena,start,count*#sizeof(T))
  fill_payload(backing[..],arena)
  arena.poison_on_rewind=true
  mem.arena_reset(arena)
  reused:=mem.push_array<T>(arena, count)
  expect(&reused[0]==&values[0])
  verify(backing[..],arena,start,count*#sizeof(T))
}
fn main() {
  for offset in 0..16 {
    for count in 0..130 {
      typed_array<u8>(count, offset)
      typed_array<u16>(count, offset)
      typed_array<u32>(count, offset)
      typed_array<u64>(count, offset)
    }
    for count in 0..8 {
      typed_array<Padded>(count, offset)
    }
  }
  absent:*mem.Arena=nil
  expect(mem.push_array<u64>(absent, 0).len==0)
  backing: [512]u8
  fill(backing[..])
  arena := mem.arena_from_buffer(backing[..mem.ArenaBufferOverhead+64])
  item := mem.push<Padded>(arena)
  start := #cast(usize, item)-#cast(usize, &backing[0])
  verify(backing[..], arena, start, #sizeof(Padded))
  before := arena.offset
  fill_payload(backing[..],arena)
  arena.poison_on_rewind = true
  mem.arena_reset(arena)
  for i in start..start+before-mem.ArenaHeader { expect(backing[i] == 221) }
  reused := mem.push<Padded>(arena)
  expect(reused == item)
  verify(backing[..], arena, start, #sizeof(Padded))
  fill(backing[..])
  mem.zero(backing[..])
  for b in backing { expect(b == 0) }
  io.println("ARENA ZERO PASS")
}
'''


def run(work):
    project = work / 'source'
    project.mkdir(exist_ok=True)
    (project / 'main.dyn').write_text(SOURCE)
    targets = [('', [])]
    qemu = shlex.split(os.environ.get('DYN_QEMU_RISCV32', ''))
    if not qemu:
        binary = shutil.which('qemu-system-riscv32')
        if binary:
            qemu = [binary]
    if qemu and shutil.which(qemu[0]):
        targets.append(('riscv32-none-soft', qemu + ['-machine', 'virt', '-cpu', 'sifive-e31', '-bios', 'none', '-nographic', '-kernel']))
    else:
        print('SKIP arena zero RV32 runtime: missing QEMU (set DYN_QEMU_RISCV32)', flush=True)
    for target, runner in targets:
        # The RV32 interpreter uses a smaller corpus spanning many word boundaries.
        source = SOURCE if not target else SOURCE.replace('0..16', '0..8').replace('0..130', '0..42')
        (project / 'main.dyn').write_text(source)
        for release in (False, True):
            name = (target or 'host') + ('-release' if release else '-debug')
            output = work / name
            command = [DYN, 'build', str(project), '--quiet', '--no-cache', '--output', str(output)]
            if release:
                command += ['--release', '--opt-level', '3', '--cpu', 'generic']
            if target:
                command += ['--target', target]
            subprocess.run(command, cwd=ROOT, check=True, timeout=120)
            # Debug deliberately checks every surrounding byte after each push.
            # Shared CI CPUs need more time for this unchanged exhaustive corpus.
            result = subprocess.run([*runner, str(output)], capture_output=True,
                                    timeout=180 if not target and not release else 60)
            assert result.returncode == 0 and b'ARENA ZERO PASS' in result.stdout, (name, result.returncode, result.stdout, result.stderr)
            print('PASS arena zero', name, flush=True)
    for failure in ('overflow', 'exhaustion'):
        count = '(~#cast(usize,0))/#sizeof(u64)+1' if failure == 'overflow' else '8'
        source = '''use mem "std/mem"
use "std/io"
use "std/panic"
failure_backing:[mem.ArenaBufferOverhead+16]u8
failure_arena:*mem.Arena
fn report(message:[]const u8) {
 if failure_arena.offset!=mem.ArenaHeader+3 { #panic("typed array failure state") }
 io.println("FAILURE STATE PASS")
}
fn main() {
 arena:=mem.arena_from_buffer(failure_backing[..])
 _=mem.push_bytes(arena,3)
 failure_arena=arena
 panic.set_handler(report)
 count:usize=COUNT
 _=mem.push_array<u64>(arena, count)
}
'''.replace('COUNT', count)
        (project / 'main.dyn').write_text(source)
        for release in (False, True):
            output = work / f'array-{failure}-{release}'
            command = [DYN, 'build', str(project), '--quiet', '--no-cache', '--output', str(output)]
            if release:
                command += ['--release', '--opt-level', '3', '--cpu', 'generic']
            subprocess.run(command, cwd=ROOT, check=True, timeout=120)
            result = subprocess.run([str(output)], capture_output=True, timeout=20)
            message = b'arena size overflow' if failure == 'overflow' else b'arena exhausted: its buffer is full'
            assert result.returncode == 101 and b'FAILURE STATE PASS\n' in result.stdout and message in result.stdout + result.stderr, (failure, release, result.returncode, result.stdout, result.stderr)
    print('PASS typed array overflow and exhaustion: exact messages and unchanged state', flush=True)

if __name__ == '__main__':
    retained = os.environ.get('DYN_ARENA_ZERO_ARTIFACTS')
    if retained:
        work = Path(retained).resolve()
        work.mkdir(parents=True, exist_ok=True)
        run(work)
    else:
        with tempfile.TemporaryDirectory(prefix='dyn-arena-zero-') as directory:
            run(Path(directory))
