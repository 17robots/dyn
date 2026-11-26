#!/usr/bin/env python3
"""Arena consumers and reuse using real std implementations."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/fail"
use "std/mem"
use "std/strings"
use "std/bytes"
use "std/encoding/ini"
use list "std/container/list"
struct Slot { free_next: *Slot, value: u64 }
const nil_slot: Slot = Slot{}
fn expect(ok: bool) { if !ok { #panic("std memory contract") } }
// Where a malformed INI text fails.
fn ini_offset(arena: *mem.Arena, source: []const u8) usize {
  _ = ini.parse(arena, source) catch err {
    case err {
      .Invalid(at) => { return at }
      _ => { #panic("ini kind") }
    }
  }
  #panic("ini accepted malformed text")
}
fn main() {
  storage: [8 * mem.KiB + mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(storage[..])
  expect(bytes.equal(strings.clone(arena, "retained"), "retained"))
  parts: [2][]const u8 = ["one", "two"]
  expect(bytes.equal(strings.join(arena, parts[..], "/"), "one/two"))
  parsed := ini.parse(arena, "[window]\nwidth=80\nheight=25\n") catch { #panic("ini.parse") }
  expect(parsed.len == 3)
  expect(bytes.equal(parsed[2].section, "window") && bytes.equal(parsed[2].value, "25"))
  before := mem.arena_used(arena)
  expect(ini_offset(arena, "x=1\ninvalid\n") == 4)
  expect(mem.arena_used(arena) == before)
  tiny_storage: [mem.ArenaBufferOverhead]u8
  tiny := mem.arena_from_buffer(tiny_storage[..])
  tiny = mem.arena_from_buffer(tiny.data[..mem.ArenaHeader])
  _ = ini.parse(tiny, "# empty") catch { #panic("ini.parse empty") }
  expect(strings.clone(tiny, "").len == 0)
  expect(mem.arena_used(tiny) == 0)

  slots := mem.push_array<Slot>(arena, 2)
  first_free: *Slot
  list.free_push(&first_free, &slots[1])
  list.free_push(&first_free, &slots[0])
  one := list.free_pop(&first_free, &nil_slot)
  two := list.free_pop(&first_free, &nil_slot)
  expect(one == &slots[0] && two == &slots[1] && list.free_pop(&first_free, &nil_slot) == &nil_slot)
  list.free_push(&first_free, one)
  expect(list.free_pop(&first_free, &nil_slot) == one && first_free == nil)

  source := mem.pages(mem.KiB)
  source.block_size = 256
  growing := mem.arena_from_source(source)
  initial := mem.push_array<u8>(growing, 32)
  expect(initial[0] == 0 && initial[31] == 0)
  for i in 0..initial.len { initial[i] = 165 }
  mem.arena_reset(growing)
  reused := mem.push_bytes(growing, 32)
  expect(reused[0] == 165 && reused[31] == 165)
  mem.arena_reset(growing)
  cleared := mem.push_array<u8>(growing, 32)
  expect(cleared[0] == 0 && cleared[31] == 0)
  expect(growing.current == growing)
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
