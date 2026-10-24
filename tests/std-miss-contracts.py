#!/usr/bin/env python3
"""Search misses use the length; failed tree parses return a stub and rewind."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use "std/sort" sort
use "std/mem" mem
use "std/encoding/mdesk" mdesk
use "std/encoding/json" json
use "std/errors" errors
fn main() {
  values:[5]i32=[2,4,4,8,10]
  for input in -2..14 {
    target:=#cast(i32,input)
    result:=sort.search(values[..],target)
    expected:usize=5
    for i in 0..5 { if values[i]==target && expected==5 { expected=i } }
    if result.index!=expected || result.found!=(expected!=5) { #panic("search miss position") }
    _=values[..result.index]
  }
  empty:[0]i32=[]
  if sort.search(empty[..],0).index!=0 || sort.search(empty[..],0).found { #panic("empty search") }
  arena:mem.Arena
  prefix:=mem.push(u8,&arena)
  prefix.*=91
  mark:=mem.arena_mark(&arena)
  parsed:=mdesk.parse(&arena,"valid: 1\nbroken: {")
  if parsed.kind!=errors.Kind.InvalidInput || parsed.error!=0 || parsed.detail!=mdesk.ErrorKind.Unclosed { #panic("mdesk error fields") }
  if parsed.ok || parsed.root!= &mdesk.nil_node || !mdesk.is_nil(parsed.root) { #panic("failed root") }
  if mem.arena_used(&arena)!=mark || prefix.*!=91 { #panic("failed parse rollback") }
  if mdesk.child(parsed.root,"valid")!= &mdesk.nil_node || mdesk.child_count(parsed.root)!=0 { #panic("stub navigation") }
  valid:=mdesk.parse(&arena,"valid: 1")
  if !valid.ok || valid.kind!=errors.Kind.None || valid.error!=0 || valid.detail!=mdesk.ErrorKind.None || mdesk.is_nil(valid.root) { #panic("parse after failure") }
  jsonmark:=mem.arena_mark(&arena)
  invalidjson:=json.parse(&arena,"{broken")
  if invalidjson.ok || invalidjson.kind!=errors.Kind.InvalidInput || invalidjson.error!=0 || invalidjson.detail!=json.ErrorKind.Syntax || invalidjson.root!= &json.nil_value || mem.arena_mark(&arena)!=jsonmark { #panic("JSON syntax fields/stub/rollback") }
  trailing:=json.parse(&arena,"null garbage")
  if trailing.ok || trailing.kind!=errors.Kind.InvalidInput || trailing.error!=0 || trailing.detail!=json.ErrorKind.TrailingData || trailing.offset!=5 || trailing.root!= &json.nil_value || mem.arena_mark(&arena)!=jsonmark { #panic("JSON trailing fields") }
  validjson:=json.parse(&arena,"null")
  if !validjson.ok || validjson.kind!=errors.Kind.None || validjson.error!=0 || validjson.detail!=json.ErrorKind.None || validjson.root.kind!=json.KindNull { #panic("JSON success fields") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-std-misses-') as directory:
    work=Path(directory);(work/'main.dyn').write_text(SOURCE)
    for mode in ('debug','release'):
        subprocess.run([DYN,'build',str(work),'--'+mode,'--quiet','--no-cache','--output',str(work/'test')],check=True,timeout=90)
        subprocess.run([str(work/'test')],check=True,timeout=10)
        print('PASS std search/tree failure contracts '+mode,flush=True)
