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
use "std/observe"
use "std/io"
struct Padded { a: u8, b: usize, c: u8 }
fn expect(ok: bool) { if !ok { #panic("arena zero contract") } }
fn fill(bytes: []u8) { for *b in bytes { b.* = 171 } }
fn verify(bytes: []u8, start: usize, size: usize) {
  for i in 0..#len(bytes) {
    if i >= start && i-start < size { expect(bytes[i] == 0) }
    else { expect(bytes[i] == 171) }
  }
}
fn typed_array($T:type, count:usize, offset:usize) {
  left:[512]u8=[]
  right:[512]u8=[]
  fill(left[..])
  fill(right[..])
  typed:=mem.arena_from_buffer(left[offset..])
  untyped:=mem.arena_from_buffer(right[offset..])
  typed_events:[4]observe.Event=[]
  untyped_events:[4]observe.Event=[]
  typed_log:=observe.log(typed_events[..])
  untyped_log:=observe.log(untyped_events[..])
  typed.events=&typed_log
  untyped.events=&untyped_log
  typed.event_resource=83
  untyped.event_resource=83
  values:=mem.push_array(T,&typed,count)
  raw:=mem.arena_push_array(&untyped,count,#sizeof(T),#alignof(T))
  expect(#len(values)==count && typed.offset==untyped.offset && typed.peak_used==untyped.peak_used)
  expect(typed_log.count==untyped_log.count)
  if count==0 { expect(raw==nil && typed.offset==0 && typed_log.count==0)
  return }
  start:=#cast(usize,&values[0])-#cast(usize,&left[0])
  other:=#cast(usize,raw)-#cast(usize,&right[0])
  expect(start==other && (#cast(usize,&values[0]) & (#alignof(T)-1))==0)
  verify(left[..],start,count*#sizeof(T))
  verify(right[..],other,count*#sizeof(T))
  expect(typed_log.count==1 && typed_events[0].kind==observe.Kind.Allocated)
  expect(typed_events[0].value==#cast(u64,count*#sizeof(T)) && typed_events[0].resource==83)
  expect(untyped_events[0].kind==typed_events[0].kind && untyped_events[0].value==typed_events[0].value)
  typed.poison_on_rewind=true
  mem.arena_reset(&typed)
  reused:=mem.push_array(T,&typed,count)
  expect(&reused[0]==&values[0] && typed_log.count==3)
  payload:=(#cast(*u8,&reused[0]))[..count*#sizeof(T)]
  for byte in payload { expect(byte==0) }
}
fn main() {
  for offset in 0..16 {
    for count in 0..8 {
      typed_array(u32,count,offset)
      typed_array(u64,count,offset)
      typed_array(Padded,count,offset)
    }
  }
  invalid:mem.Arena
  invalid.offset=1
  expect(#len(mem.push_array(u64,&invalid,0))==0 && invalid.offset==1 && invalid.allocation_failures==0)
  absent:*mem.Arena=nil
  expect(#len(mem.push_array(u64,absent,0))==0)
  backing: [320]u8
  for offset in 0..16 {
    for size in 0..130 {
      for alignment in [1, 2, 4, 8, 16] {
        fill(backing[..])
        arena := mem.arena_from_buffer(backing[offset..300])
        result := mem.arena_try_push(&arena, size, #cast(usize, alignment))
        expect(result.ok && result.size == size)
        if size == 0 {
          expect(result.memory == nil && arena.offset == 0)
          verify(backing[..], 0, 0)
        } else {
          start := #cast(usize, result.memory)-#cast(usize, &backing[0])
          expect(#cast(usize, result.memory) % #cast(usize, alignment) == 0)
          expect(arena.offset == start-offset+size)
          verify(backing[..], start, size)
          for extra in 0..34 {
            fill(backing[..])
            arena.offset = start-offset+size
            expect(mem.arena_try_extend(&arena, result.memory, size, extra))
            verify(backing[..], start+size, extra)
          }
        }
      }
    }
  }
  fill(backing[..])
  arena := mem.arena_from_buffer(backing[..64])
  events: [16]observe.Event
  log := observe.log(events[..])
  arena.events = &log
  arena.event_resource = 77
  zero := mem.arena_try_push(&arena, 0, 1)
  expect(zero.ok && zero.memory == nil && log.count == 0)
  item := mem.push(Padded, &arena)
  start := #cast(usize, item)-#cast(usize, &backing[0])
  verify(backing[..], start, #sizeof(Padded))
  expect(log.count == 1 && events[0].kind == observe.Kind.Allocated)
  expect(events[0].value == #cast(u64, #sizeof(Padded)) && events[0].resource == 77)
  before := arena.offset
  fill(backing[..])
  failed := mem.arena_try_push(&arena, 65, 1)
  expect(!failed.ok && failed.error == mem.ErrorKind.Capacity && arena.offset == before)
  expect(arena.allocation_failures == 1 && log.count == 2)
  expect(events[1].kind == observe.Kind.AllocationFailed && events[1].value == #cast(u64, before))
  expect(!mem.arena_try_extend(&arena, #cast(*u8, item), #sizeof(Padded), 65))
  verify(backing[..], 0, 0)
  expect(log.count == 2 && arena.offset == before)
  arena.poison_on_rewind = true
  mem.arena_reset(&arena)
  for i in 0..before { expect(backing[i] == 221) }
  reused := mem.push(Padded, &arena)
  expect(reused == item)
  verify(backing[..], start, #sizeof(Padded))
  expect(log.count == 4 && events[2].kind == observe.Kind.Reclaimed && events[3].kind == observe.Kind.Allocated)
  fill(backing[..])
  mem.zero(backing[..])
  for b in backing { expect(b == 0) }
  _ = io.println(io.stdout(), "ARENA ZERO PASS")
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
        source = SOURCE if not target else SOURCE.replace('0..16', '0..8').replace('0..130', '0..42').replace('0..34', '0..10')
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
            result = subprocess.run([*runner, str(output)], capture_output=True, timeout=60)
            assert result.returncode == 0 and b'ARENA ZERO PASS' in result.stdout, (name, result.returncode, result.stdout, result.stderr)
            print('PASS arena zero', name, flush=True)
    for failure in ('overflow', 'exhaustion'):
        for typed in (False, True):
            call = 'mem.push_array(u64,&arena,count)' if typed else 'mem.arena_push_array(&arena,count,#sizeof(u64),#alignof(u64))'
            count = '(~#cast(usize,0))/#sizeof(u64)+1' if failure == 'overflow' else '3'
            failures = '0' if failure == 'overflow' else '1'
            source = '''use "std/mem" mem
use "std/observe"
use "std/io"
fn cleanup(arena:*mem.Arena, log:*observe.Log) {
 if arena.offset!=3 || arena.allocation_failures!=FAILURES || log.count!=EVENTS { #panic("typed array failure state") }
 _=io.println(io.stdout(),"FAILURE STATE PASS")
}
fn main() {
 backing:[16]u8=[]
 arena:=mem.arena_from_buffer(backing[..])
 events:[4]observe.Event=[]
 log:=observe.log(events[..])
 arena.events=&log
 _=mem.push_bytes_uninit(&arena,3)
 defer cleanup(&arena,&log)
 count:usize=COUNT
 _=CALL
}
'''.replace('FAILURES', failures).replace('EVENTS', '1' if failure == 'overflow' else '2').replace('COUNT', count).replace('CALL', call)
            (project / 'main.dyn').write_text(source)
            for release in (False, True):
                output = work / f'array-{failure}-{typed}-{release}'
                command = [DYN, 'build', str(project), '--quiet', '--no-cache', '--output', str(output)]
                if release:
                    command += ['--release', '--opt-level', '3', '--cpu', 'generic']
                subprocess.run(command, cwd=ROOT, check=True, timeout=120)
                result = subprocess.run([str(output)], capture_output=True, timeout=20)
                message = b'arena size overflow' if failure == 'overflow' else b'arena exhausted or alignment invalid'
                assert result.returncode == 101 and b'FAILURE STATE PASS\n' in result.stdout and message in result.stdout + result.stderr, (failure, typed, release, result.returncode, result.stdout, result.stderr)
    print('PASS typed/untyped array overflow and exhaustion: exact messages, cleanup, marks and events', flush=True)


if __name__ == '__main__':
    retained = os.environ.get('DYN_ARENA_ZERO_ARTIFACTS')
    if retained:
        work = Path(retained).resolve()
        work.mkdir(parents=True, exist_ok=True)
        run(work)
    else:
        with tempfile.TemporaryDirectory(prefix='dyn-arena-zero-') as directory:
            run(Path(directory))
