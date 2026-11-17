#!/usr/bin/env python3
"""Search misses use the length; failed tree parses return a stub and rewind."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use "std/fail"
use "std/sort" sort
use "std/mem" mem
use "std/encoding/mdesk" mdesk
use "std/encoding/json" json
fn main() {
  values:[5]i32=[2,4,4,8,10]
  for input: isize in -2..14 {
    target:=#cast(i32,input)
    result:=sort.search(values[..],target)
    expected:usize=5
    for i in 0..5 { if values[i]==target && expected==5 { expected=i } }
    if result.index!=expected || result.found!=(expected!=5) { #panic("search miss position") }
    _=values[..result.index]
  }
  empty:[0]i32
  if sort.search(empty[..],0).index!=0 || sort.search(empty[..],0).found { #panic("empty search") }
  arena := mem.arena_alloc(0)
  defer mem.arena_release(arena)
  prefix:=mem.push(u8,arena)
  prefix.*=91
  mark:=mem.arena_mark(arena)
  broken:fail.Status
  parsed:=mdesk.parse(arena,&broken,"valid: 1\nbroken: {")
  if broken.failure.kind != fail.Kind.InvalidInput { #panic("mdesk error fields") }
  if parsed!= &mdesk.nil_node || !mdesk.is_nil(parsed) { #panic("failed root") }
  if mem.arena_mark(arena)!=mark || prefix.*!=91 { #panic("failed parse rollback") }
  if mdesk.child(parsed,"valid")!= &mdesk.nil_node || mdesk.child_count(parsed)!=0 { #panic("stub navigation") }
  status:fail.Status
  valid:=mdesk.parse(arena,&status,"valid: 1")
  if status.failed || mdesk.is_nil(valid) { #panic("parse after failure") }
  jsonmark:=mem.arena_mark(arena)
  syntax:fail.Status
  invalidjson:=json.parse(arena,&syntax,"{broken")
  if syntax.failure.kind != fail.Kind.InvalidInput || invalidjson!= &json.nil_value || mem.arena_mark(arena)!=jsonmark { #panic("JSON syntax fields/stub/rollback") }
  trailing:fail.Status
  trailing_root:=json.parse(arena,&trailing,"null garbage")
  if trailing.failure.kind != fail.Kind.InvalidInput || !mem.equal(fail.message_text(&trailing.failure), "trailing data") || trailing.failure.offset!=5 || trailing_root!= &json.nil_value || mem.arena_mark(arena)!=jsonmark { #panic("JSON trailing fields") }
  validjson:=json.parse(arena,&status,"null")
  if status.failed || validjson.kind!=json.KindNull { #panic("JSON success fields") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-std-misses-') as directory:
    work=Path(directory);(work/'main.dyn').write_text(SOURCE)
    for mode in ('debug','release'):
        subprocess.run([DYN,'build',str(work),'--'+mode,'--quiet','--no-cache','--output',str(work/'test')],check=True,timeout=90)
        subprocess.run([str(work/'test')],check=True,timeout=10)
        print('PASS std search/tree failure contracts '+mode,flush=True)
