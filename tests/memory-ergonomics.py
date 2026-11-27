#!/usr/bin/env python3
"""Typed arrays, readable units, bounded growth and reuse in real allocations, debug/release."""
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
  created := mem.arena_alloc(mem.KiB)
  defer { mem.arena_release(created) }
  items := mem.push_array<Item>(created, 7)
  for *item in items {
    expect(item.tag == 0 && item.value == 0)
    item.value = 42
  }
  expect(items[6].value == 42)
  expect(mem.MiB == 1024 * mem.KiB && mem.GiB == 1024 * mem.MiB)

  source := mem.pages(4 * mem.KiB)
  source.block_size = 512
  chain := mem.arena_from_source(source)
  defer { mem.arena_release(chain) }
  first := mem.push<u64>(chain)
  first.* = 42
  _ = mem.push_bytes(chain, 400)
  second := mem.push<u64>(chain)
  second.* = 17
  _ = mem.push_bytes(chain, 400)
  expect(chain.current != chain && mem.arena_used(chain) >= 816)
  expect(first.* == 42 && second.* == 17)
  mem.arena_reset(chain)
  expect(mem.arena_used(chain) == 0 && chain.current == chain)
  for cycle in 0..100 {
    _ = mem.push_bytes(chain, 400)
    _ = mem.push_bytes(chain, 400)
    mem.arena_reset(chain)
    expect(chain.current == chain)
  }
  tight := mem.arena_from_source(mem.pages(mem.ArenaHeader))
  expect(mem.push_bytes(tight, 0).len == 0 && tight.current == tight)
  mem.arena_release(tight)
  unbounded := mem.arena_alloc(0)
  _ = mem.push_bytes(unbounded, 4096)
  expect(unbounded.current == unbounded)
  mem.arena_release(unbounded)
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
print('PASS memory units, typed arrays, bounded growth, retention and repeated reuse (debug/release)')
