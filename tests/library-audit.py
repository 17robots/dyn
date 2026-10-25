#!/usr/bin/env python3
"""Regressions for JSON control escapes/storage, decimal rounding, and container churn."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get("DYN", ROOT / "build/dyn-release")).resolve())
CASES = {
    'json-format': r'''
use "std/encoding/json" json
use "std/mem" memory
use "std/fmt" fmt
use "std/bytes" bytes
fn expect_decimal(value:f64, precision:usize, expected:[]const u8) {
  output:[128 + memory.ArenaBufferOverhead]u8=[]
  scratch:=memory.arena_from_buffer(output[..])
  if !bytes.equal(fmt.f64_decimal(scratch,value,precision),expected) { #panic("decimal rounding") }
}
fn main() {
  backing:[16384]u8=[]
  arena:=memory.arena_from_buffer(backing[..])
  arena.poison_on_rewind=true
  for i in 0..32 {
    control:[1]u8=[]
    control[0]=#cast(u8, i)
    encoded:[16 + memory.ArenaBufferOverhead]u8=[]
    encoded_arena:=memory.arena_from_buffer(encoded[..])
    written:=json.write_string(encoded_arena,control[..])
    if #len(written)==0 { #panic("control escape") }
    parsed:=json.parse(arena,written)
    if !parsed.ok || #len(parsed.root.text)!=1 || parsed.root.text[0]!=control[0] { #panic("control roundtrip") }
    roundtrip:[16 + memory.ArenaBufferOverhead]u8=[]
    roundtrip_arena:=memory.arena_from_buffer(roundtrip[..])
    if !bytes.equal(json.encode(roundtrip_arena,parsed.root),written) { #panic("node encode") }
  }
  memory.arena_reset(arena)
  source:[6002]u8=[]
  source[0]='"'
  for i in 0..1000 { _=memory.copy(source[1+i*6..],"\\u0061") }
  source[6001]='"'
  parsed:=json.parse(arena,source[..])
  if !parsed.ok || #len(parsed.root.text)!=1000 || memory.arena_used(arena)!=#sizeof(json.Value)+1000 { #panic("retained string size") }
  for byte in parsed.root.text { if byte!='a' { #panic("rewind changed retained bytes") } }
  expect_decimal(4503599627370497.0,0,"4503599627370497")
  expect_decimal(9007199254740991.0,0,"9007199254740991")
  expect_decimal(-4503599627370497.0,0,"-4503599627370497")
  expect_decimal(1.5,0,"2")
  expect_decimal(-1.5,0,"-2")
  expect_decimal(1.125,2,"1.13")
  expect_decimal(9.999,2,"10")
}
''',
    'containers': r'''
use "std/mem" mem
use "std/container/hash" hash
use "std/container/list" list
use "std/container/slot_map" slots
use "std/fmt" fmt
struct Entry {
  generation: u32,
  key: []const u8,
  hash: u64,
  hash_next: *Entry,
  free_next: *Entry,
  value: usize,
}
const nil_entry: Entry = Entry{}
fn main() {
  owned := mem.arena_create(1000000)
  table := hash.slots(Entry, owned, 8)
  entries := mem.push_array(Entry, owned, 128)
  first_free: *Entry
  for i in 0..128 {
    list.free_push(&first_free, &entries[127 - i])
  }
  live: [128]*Entry = []
  handles: [128]slots.Handle = []
  scratch := mem.arena_create(0)
  seed: u64 = 7
  for step in 0..4000 {
    seed = (seed * 1664525 + 1013904223) % 4294967296
    index := #cast(usize, (seed % 128))
    text := fmt.u64_decimal(scratch, #cast(u64, index))
    if (seed / 128) % 2 == 0 {
      if live[index] == nil {
        entry := list.free_pop(&first_free, &nil_entry)
        if entry == &nil_entry { #panic("free list exhausted") }
        slots.reset(entry)
        entry.key = fmt.u64_decimal(owned, #cast(u64, index))
        entry.value = index
        entry.hash = hash.hash_bytes(1, entry.key)
        hash.insert(table, entry)
        live[index] = entry
        handles[index] = slots.handle_of(entries, entry)
      }
    } else if live[index] != nil {
      entry := live[index]
      if !hash.remove(table, entry) { #panic("remove") }
      slots.retire(entry)
      list.free_push(&first_free, entry)
      if slots.resolve(entries, handles[index], &nil_entry) != &nil_entry { #panic("stale handle") }
      live[index] = nil
    }
    if step % 13 == 0 {
      for i in 0..128 {
        name := fmt.u64_decimal(scratch, #cast(u64, i))
        found := hash.find(table, hash.hash_bytes(1, name), name, &nil_entry)
        if (found != &nil_entry) != (live[i] != nil) { #panic("collision chain") }
        if live[i] != nil {
          if found.value != i || slots.resolve(entries, handles[i], &nil_entry) != found { #panic("value") }
        }
      }
    }
  }
  mem.arena_release(owned)
}
''',
}
with tempfile.TemporaryDirectory(prefix="dyn-library-audit-") as temporary:
    for name, source in CASES.items():
        project = Path(temporary) / name
        project.mkdir()
        (project / "main.dyn").write_text(source)
        for release in (False, True):
            output = project / "program"
            subprocess.run([DYN, "build", str(project), "--no-cache", "--quiet", "--output", str(output)] + (["--release"] if release else []), check=True, timeout=90)
            subprocess.run([str(output)], check=True, timeout=15)
print("PASS JSON control roundtrip/storage, decimal rounding, and container churn (debug/release)")
