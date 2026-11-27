#!/usr/bin/env python3
"""Search misses use the length; failed tree parses fail at their offset and rewind."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use parse "std/parse"
use sort "std/sort"
use mem "std/mem"
use mdesk "std/encoding/mdesk"
use json "std/encoding/json"
fn mdesk_offset(arena:*mem.Arena, source:[]const u8) usize {
  _=mdesk.parse(arena,source) catch err { return parse.offset(err) }
  #panic("mdesk accepted malformed text")
}
fn json_offset(arena:*mem.Arena, source:[]const u8) usize {
  _=json.parse(arena,source) catch err { return parse.offset(err) }
  #panic("JSON accepted malformed text")
}
fn main() {
  values:[5]i32=[2,4,4,8,10]
  for input: isize in -2..14 {
    target:=#cast(i32,input)
    index:=sort.search(values[..],target)
    expected:usize=5
    for i in 0..5 { if values[i]==target && expected==5 { expected=i } }
    if index!=expected { #panic("search miss position") }
    _=values[..index]
  }
  empty:[0]i32
  if sort.search(empty[..],0)!=0 { #panic("empty search") }
  arena := mem.arena_alloc(0)
  defer mem.arena_release(arena)
  prefix:=mem.push<u8>(arena)
  prefix.*=91
  mark:=mem.arena_mark(arena)
  if mdesk_offset(arena,"valid: 1\nbroken: {") != 17 { #panic("mdesk error offset") }
  if mem.arena_mark(arena)!=mark || prefix.*!=91 { #panic("failed parse rollback") }
  valid:=mdesk.parse(arena,"valid: 1") catch { #panic("parse after failure") }
  if mdesk.is_nil(valid) { #panic("parse after failure") }
  jsonmark:=mem.arena_mark(arena)
  if json_offset(arena,"{broken") != 1 || mem.arena_mark(arena)!=jsonmark { #panic("JSON syntax offset/rollback") }
  if json_offset(arena,"null garbage") != 5 || mem.arena_mark(arena)!=jsonmark { #panic("JSON trailing offset") }
  validjson:=json.parse(arena,"null") catch { #panic("JSON success") }
  if validjson.kind!=json.KindNull { #panic("JSON success fields") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-std-misses-') as directory:
    work=Path(directory);(work/'main.dyn').write_text(SOURCE)
    for mode in ('debug','release'):
        subprocess.run([DYN,'build',str(work),'--'+mode,'--quiet','--no-cache','--output',str(work/'test')],check=True,timeout=90)
        subprocess.run([str(work/'test')],check=True,timeout=10)
        print('PASS std search/tree failure contracts '+mode,flush=True)
