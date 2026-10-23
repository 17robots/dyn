#!/usr/bin/env python3
"""Arena consumers and reuse using real std implementations."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/mem"
use "std/strings"
use "std/encoding/ini"
use "std/container/list" list
struct Slot { free_next: *Slot, value: u64 }
const nil_slot: Slot = Slot{}
fn expect(ok: bool) { if !ok { #panic("std memory contract") } }
fn fixed_empty(arena: *mem.Arena) {
  before := mem.arena_snapshot(arena)
  empty := mem.arena_try_push(arena, 0, 1)
  expect(empty.ok && empty.memory == nil && empty.size == 0)
  for i in 0..2 {
    failed := mem.arena_try_push(arena, 1, 1)
    expect(!failed.ok && failed.error == mem.ErrorKind.Capacity)
    after := mem.arena_snapshot(arena)
    expect(after.capacity == 0 && after.used == 0 && !after.owns_memory)
    expect(after.peak_used == before.peak_used)
    expect(after.allocation_failures == before.allocation_failures + i + 1)
    mem.arena_reset(arena)
    mem.arena_rewind(arena, 0)
  }
}
fn main() {
  no_storage: []u8
  empty_fixed := mem.arena_from_buffer(no_storage)
  fixed_empty(&empty_fixed)
  moved := mem.arena_take(&empty_fixed)
  fixed_empty(&moved)
  mem.arena_release(&moved)
  mem.arena_release(&moved)
  sentinel: [1]u8 = [91]
  empty_view := mem.arena_from_buffer(sentinel[..0])
  fixed_empty(&empty_view)
  expect(sentinel[0] == 91)
  parent := mem.arena_from_buffer(sentinel[..])
  child := mem.arena_sub(&parent, 0)
  fixed_empty(&child)
  expect(mem.arena_used(&parent) == 0 && sentinel[0] == 91)
  _ = mem.arena_try_push(&parent, 1, 1)
  full := mem.arena_try_push(&parent, 1, 1)
  expect(!full.ok && full.error == mem.ErrorKind.Capacity)
  expect(!parent.owns_memory && mem.arena_capacity(&parent) == 1 && mem.arena_used(&parent) == 1)
  storage: [8 * mem.KiB]u8
  arena := mem.arena_from_buffer(storage[..])
  expect(strings.equal(strings.clone(&arena, "retained"), "retained"))
  parts: [2][]const u8 = ["one", "two"]
  expect(strings.equal(strings.join(&arena, parts[..], "/"), "one/two"))
  parsed := ini.parse(&arena, "[window]\nwidth=80\nheight=25\n")
  expect(parsed.ok && #len(parsed.value) == 3)
  expect(strings.equal(parsed.value[2].section, "window") && strings.equal(parsed.value[2].value, "25"))
  before := mem.arena_used(&arena)
  syntax := ini.parse(&arena, "x=1\ninvalid\n")
  expect(!syntax.ok && syntax.kind == ini.ErrorKind.Syntax && syntax.line == 2)
  expect(mem.arena_used(&arena) == before)
  tiny_storage: [1]u8
  tiny := mem.arena_from_buffer(tiny_storage[..])
  expect(ini.parse(&tiny, "# empty").ok)
  expect(#len(strings.clone(&tiny, "")) == 0)
  expect(mem.arena_used(&tiny) == 0)

  slots := mem.push_array(Slot, &arena, 2)
  first_free: *Slot
  list.free_push(&first_free, &slots[1])
  list.free_push(&first_free, &slots[0])
  one := list.free_pop(&first_free, &nil_slot)
  two := list.free_pop(&first_free, &nil_slot)
  expect(one == &slots[0] && two == &slots[1] && list.free_pop(&first_free, &nil_slot) == &nil_slot)
  list.free_push(&first_free, one)
  expect(list.free_pop(&first_free, &nil_slot) == one && first_free == nil)

  growing := mem.growing_create_bounded(128, mem.KiB)
  initial := mem.growing_push(&growing, 32, 1)[..32]
  expect(initial[0] == 0 && initial[31] == 0)
  for i in 0..#len(initial) { initial[i] = 165 }
  mem.growing_reset(&growing)
  reused := mem.growing_try_push_uninit(&growing, 32, 1)
  expect(reused.ok && reused.memory[..32][0] == 165 && reused.memory[..32][31] == 165)
  mem.growing_reset(&growing)
  cleared := mem.growing_push(&growing, 32, 1)[..32]
  expect(cleared[0] == 0 && cleared[31] == 0)
  expect(mem.growing_snapshot(&growing).blocks == 1)
  mem.growing_release(&growing)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-std-memory-') as temporary:
    base = Path(temporary)
    for name, source in [('consumers', SOURCE)]:
        project = base / name
        project.mkdir()
        (project / 'main.dyn').write_text(source)
        for release in (False, True):
            output = project / ('release' if release else 'debug')
            subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--output', str(output),
                            *(['--release'] if release else [])], cwd=ROOT, check=True, timeout=120)
            subprocess.run([str(output)], check=True, timeout=10)
print('PASS std arena consumers, pool reuse, growing zeroing, release/trim (debug/release)')
