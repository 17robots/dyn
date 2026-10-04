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
  output:[128]u8=[]
  if !bytes.equal(fmt.f64_decimal(output[..],value,precision),expected) { #panic("decimal rounding") }
}
fn main() {
  backing:[16384]u8=[]
  arena:=memory.arena_from_buffer(backing[..])
  arena.poison_on_rewind=true
  for i in 0..32 {
    control:[1]u8=[]
    control[0]=#cast(u8) i
    encoded:[16]u8=[]
    written:=json.write_string(encoded[..],control[..])
    if #len(written)==0 { #panic("control escape") }
    parsed:=json.parse(&arena,written)
    if !parsed.ok || #len(parsed.root.text)!=1 || parsed.root.text[0]!=control[0] { #panic("control roundtrip") }
    roundtrip:[16]u8=[]
    if !bytes.equal(json.encode(roundtrip[..],parsed.root),written) { #panic("node encode") }
  }
  memory.arena_reset(&arena)
  source:[6002]u8=[]
  source[0]='"'
  for i in 0..1000 { _=memory.copy(source[1+i*6..],"\\u0061") }
  source[6001]='"'
  parsed:=json.parse(&arena,source[..])
  if !parsed.ok || #len(parsed.root.text)!=1000 || memory.arena_used(&arena)!=#sizeof(json.Value)+1000 { #panic("retained string size") }
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
use "std/container/string_map" maps
use "std/container/slot_map" slots
use "std/fmt" fmt
fn main() {
  owned := mem.arena_create(1000000)
  map := maps.Map{}
  live: [128]bool = []
  key: [32]u8 = []
  seed: u64 = 7
  for step in 0..4000 {
    seed = (seed * 1664525 + 1013904223) % 4294967296
    index := #cast(usize) (seed % 128)
    text := fmt.u64_decimal(key[..], #cast(u64) index)
    if (seed / 128) % 2 == 0 {
      if maps.put(&map, &owned.arena, text, index) != maps.ErrorKind.None { #panic("put") }
      live[index] = true
    } else {
      if maps.remove(&map, text) != live[index] { #panic("remove") }
      live[index] = false
    }
    if step % 13 == 0 {
      count: usize = 0
      for i in 0..128 {
        found := maps.get(&map, fmt.u64_decimal(key[..], #cast(u64) i))
        if found.found != live[i] { #panic("collision chain") }
        if live[i] {
          count += 1
          if found.value != i { #panic("value") }
        }
      }
      if count != map.length { #panic("length") }
    }
  }
  data: [4]u8 = []
  generations: [4]u32 = [0, 4294967294, 0, 0]
  occupied: [1]u64 = []
  state := slots.init(data[..], generations[..], occupied[..], 1)
  handles: [3]slots.Handle = []
  byte: [1]u8 = [42]
  for i in 0..3 { handles[i] = slots.insert(&state, byte[..]) }
  if handles[0].index != 0 || handles[1].index != 2 || handles[2].index != 3 { #panic("retired slot") }
  if slots.insert(&state, byte[..]).generation != 0 { #panic("full") }
  if !slots.remove(&state, handles[2]) || !slots.remove(&state, handles[0]) { #panic("remove slot") }
  fresh := slots.insert(&state, byte[..])
  if fresh.index != 0 || slots.get(&state, handles[0]).ok { #panic("reuse") }
  if slots.insert(&state, byte[..]).index != 3 { #panic("second reuse") }
  state = slots.init(data[..], generations[..], occupied[..], 1)
  if slots.get(&state, fresh).ok || slots.insert(&state, byte[..]).index != 0 { #panic("reinit") }
  _ = mem.arena_release(&owned.arena)
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
