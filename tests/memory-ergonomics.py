#!/usr/bin/env python3
"""Fallible array sizing and readable units in real allocations, debug/release."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/mem"
struct Item { tag: u8, value: u64 }
fn expect(ok: bool) { if !ok { #panic("memory ergonomics contract") } }
fn main() {
  created := mem.arena_create(mem.KiB)
  expect(created.ok)
  defer { expect(mem.arena_release(&created.arena).ok) }
  count: usize = 7
  size := mem.size_for(count, #sizeof(Item))
  expect(size.ok)
  allocation := mem.arena_push_array(&created.arena, count, #sizeof(Item), #alignof(Item))
  expect(allocation.ok)
  items := (#cast(*Item) allocation.memory)[..count]
  for *item in items {
    expect(item.tag == 0 && item.value == 0)
    item.value = 42
  }
  expect(items[6].value == 42)
  maximum := #cast(usize) -1
  edge := mem.size_for(maximum / 8, 8)
  expect(edge.ok && edge.bytes == maximum - maximum % 8)
  before := mem.arena_used(&created.arena)
  overflow := mem.size_for(maximum / 8 + 1, 8)
  expect(!overflow.ok && overflow.bytes == 0)
  expect(mem.arena_used(&created.arena) == before && items[6].value == 42)
  failed_array := mem.arena_push_array(&created.arena, maximum, #sizeof(Item), #alignof(Item))
  expect(!failed_array.ok && failed_array.error == mem.ErrorKind.Overflow)
  expect(mem.arena_used(&created.arena) == before && items[6].value == 42)
  exact := mem.size_for(maximum, 1)
  expect(exact.ok && exact.bytes == maximum)
  zero_count := mem.size_for(0, maximum)
  zero_size := mem.size_for(maximum, 0)
  expect(zero_count.ok && zero_count.bytes == 0)
  expect(zero_size.ok && zero_size.bytes == 0)
  expect(mem.MiB == 1024 * mem.KiB && mem.GiB == 1024 * mem.MiB)

  chain := mem.growing_create_bounded(128, mem.KiB)
  defer { expect(mem.growing_release(&chain).ok) }
  first := mem.growing_push_or_panic(&chain, 128, 8)
  first.* = 42
  second := mem.growing_push_or_panic(&chain, 128, 8)
  second.* = 17
  snapshot := mem.growing_snapshot(&chain)
  expect(snapshot.blocks == 2 && snapshot.used >= 256)
  expect(snapshot.backing_bytes <= mem.KiB)
  // Live blocks cannot be trimmed, even when the target is zero.
  expect(mem.growing_trim(&chain, 0).ok)
  expect(mem.growing_snapshot(&chain).backing_bytes == snapshot.backing_bytes)
  expect(first.* == 42 && second.* == 17)
  too_large := mem.growing_push(&chain, mem.KiB, 1)
  expect(!too_large.ok && too_large.error == mem.ErrorKind.Capacity)
  expect(mem.growing_snapshot(&chain).backing_bytes == snapshot.backing_bytes)
  expect(first.* == 42 && second.* == 17)
  mem.growing_reset(&chain)
  expect(mem.growing_snapshot(&chain).used == 0)
  // Keep one live block and trim an empty tail; append must still work afterwards.
  live := mem.growing_push_or_panic(&chain, 128, 8)
  live.* = 91
  expect(mem.growing_trim(&chain, 0).ok)
  expect(mem.growing_snapshot(&chain).blocks == 1 && live.* == 91)
  _ = mem.growing_push_or_panic(&chain, 128, 8)
  expect(mem.growing_snapshot(&chain).blocks == 2 && live.* == 91)
  for cycle in 0..100 {
    mem.growing_reset(&chain)
    expect(mem.growing_trim(&chain, 0).ok)
    expect(mem.growing_snapshot(&chain).backing_bytes == 0)
    expect(chain.first == nil && chain.current == nil)
    _ = mem.growing_push_or_panic(&chain, 64, 8)
  }
  empty := mem.growing_create_bounded(128, 0)
  expect(mem.growing_push(&empty, 0, 1).ok)
  expect(!mem.growing_push(&empty, 1, 1).ok)
  expect(mem.growing_snapshot(&empty).blocks == 0)
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-memory-ergonomics-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    for release in (False, True):
        output = project / ('release' if release else 'debug')
        subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet',
                        '--output', str(output), *(['--release'] if release else [])],
                       cwd=ROOT, check=True, timeout=120)
        subprocess.run([str(output)], check=True, timeout=10)
print('PASS memory units, checked arrays, bounded growth, retention, trim and repeated reuse (debug/release)')
