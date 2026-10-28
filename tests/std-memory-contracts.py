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
use "std/errors"
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
  no_payload: [mem.ArenaBufferOverhead]u8
  empty_fixed := mem.arena_from_buffer(no_payload[..])
  empty_fixed = mem.arena_from_buffer(empty_fixed.data[..mem.ArenaHeader])
  fixed_empty(empty_fixed)
  // Pointer ownership transfers explicitly; the old owner becomes inactive.
  moved := empty_fixed
  empty_fixed = nil
  expect(empty_fixed == nil)
  fixed_empty(moved)
  mem.arena_release(moved)
  moved = nil
  mem.arena_release(moved)
  // Reconstruct a released borrowed header before reusing its caller storage.
  empty_fixed = mem.arena_from_buffer(no_payload[..])
  empty_fixed = mem.arena_from_buffer(empty_fixed.data[..mem.ArenaHeader])
  fixed_empty(empty_fixed)
  mem.arena_release(empty_fixed)
  sentinel: [mem.ArenaBufferOverhead + 2]u8
  mem.fill(sentinel[..], 91)
  empty_view := mem.arena_from_buffer(sentinel[1..#len(sentinel)-1])
  empty_view = mem.arena_from_buffer(empty_view.data[..mem.ArenaHeader])
  fixed_empty(empty_view)
  expect(sentinel[0] == 91 && sentinel[#len(sentinel)-1] == 91)
  parent_storage: [mem.ArenaHeader + 1 + mem.ArenaBufferOverhead]u8
  parent := mem.arena_from_buffer(parent_storage[..])
  parent = mem.arena_from_buffer(parent.data[..2 * mem.ArenaHeader + 1])
  child := mem.arena_sub(parent, mem.ArenaHeader)
  fixed_empty(child)
  expect(mem.arena_used(parent) == mem.ArenaHeader)
  allocated := mem.arena_try_push(parent, 1, 1)
  expect(allocated.ok)
  allocated.memory.* = 91
  full := mem.arena_try_push(parent, 1, 1)
  expect(!full.ok && full.error == mem.ErrorKind.Capacity)
  expect(!parent.owns_memory && mem.arena_capacity(parent) == mem.ArenaHeader + 1 && mem.arena_used(parent) == mem.ArenaHeader + 1)
  expect(allocated.memory.* == 91)
  storage: [8 * mem.KiB + mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(storage[..])
  expect(strings.equal(strings.clone(arena, "retained"), "retained"))
  parts: [2][]const u8 = ["one", "two"]
  expect(strings.equal(strings.join(arena, parts[..], "/"), "one/two"))
  parsed := ini.parse(arena, "[window]\nwidth=80\nheight=25\n")
  expect(parsed.ok && #len(parsed.value) == 3)
  expect(strings.equal(parsed.value[2].section, "window") && strings.equal(parsed.value[2].value, "25"))
  before := mem.arena_used(arena)
  syntax := ini.parse(arena, "x=1\ninvalid\n")
  expect(!syntax.ok && syntax.kind == errors.Kind.InvalidInput && syntax.error == 0 && syntax.detail == ini.ErrorKind.Syntax && syntax.offset == 4 && syntax.line == 2)
  expect(mem.arena_used(arena) == before)
  tiny_storage: [mem.ArenaBufferOverhead]u8
  tiny := mem.arena_from_buffer(tiny_storage[..])
  tiny = mem.arena_from_buffer(tiny.data[..mem.ArenaHeader])
  expect(ini.parse(tiny, "# empty").ok)
  expect(#len(strings.clone(tiny, "")) == 0)
  expect(mem.arena_used(tiny) == 0)

  slots := mem.push_array(Slot, arena, 2)
  first_free: *Slot
  list.free_push(&first_free, &slots[1])
  list.free_push(&first_free, &slots[0])
  one := list.free_pop(&first_free, &nil_slot)
  two := list.free_pop(&first_free, &nil_slot)
  expect(one == &slots[0] && two == &slots[1] && list.free_pop(&first_free, &nil_slot) == &nil_slot)
  list.free_push(&first_free, one)
  expect(list.free_pop(&first_free, &nil_slot) == one && first_free == nil)

  growing := mem.arena_create_bounded(256, mem.KiB)
  initial := mem.arena_push(growing, 32, 1)[..32]
  expect(initial[0] == 0 && initial[31] == 0)
  for i in 0..#len(initial) { initial[i] = 165 }
  mem.arena_reset(growing)
  reused := mem.arena_push_uninit(growing, 32, 1)[..32]
  expect(reused[0] == 165 && reused[31] == 165)
  mem.arena_reset(growing)
  cleared := mem.arena_push(growing, 32, 1)[..32]
  expect(cleared[0] == 0 && cleared[31] == 0)
  expect(mem.arena_snapshot(growing).blocks == 1)
  mem.arena_release(growing)
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
print('PASS std arena consumers, pool reuse, bounded arena zeroing and reuse (debug/release)')
