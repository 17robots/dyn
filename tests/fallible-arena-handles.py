#!/usr/bin/env python3
"""Fallible additions preserve published pointer handles and bounded payloads."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
SOURCE = '''use "std/mem"
fn check(ok: bool) { if !ok { #panic("fallible arena handles") } }
fn main() {
  bad := mem.arena_try_create_bounded(64, 64)
  check(!bad.ok && bad.arena == nil && bad.error == mem.ErrorKind.Capacity)
  mem.arena_release(bad.arena)
  created := mem.arena_try_create(0)
  check(created.ok && created.arena != nil)
  check(mem.arena_used(created.arena) == 0)
  mem.arena_release(created.arena)
  bounded := mem.arena_try_create_bounded(mem.ArenaHeader + 64, mem.ArenaHeader + 64)
  check(bounded.ok)
  arena := bounded.arena
  bytes := mem.arena_try_push_uninit(arena, 64, 1)
  check(bytes.ok)
  bytes.memory.* = 91
  mark := mem.arena_mark(arena)
  failed := mem.arena_try_push_uninit(arena, 1, 1)
  check(!failed.ok && failed.error == mem.ErrorKind.Capacity)
  check(mem.arena_mark(arena) == mark && bytes.memory.* == 91)
  check(!mem.arena_try_extend(arena, bytes.memory, 64, 1))
  check(mem.arena_mark(arena) == mark && bytes.memory.* == 91)
  mem.arena_reset(arena)
  reused := mem.arena_try_push_uninit(arena, 64, 1)
  check(reused.ok && reused.memory.* == 91)
  mem.arena_release(arena)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-fallible-handles-') as temporary:
    project=Path(temporary)
    (project/'main.dyn').write_text(SOURCE)
    for mode in ('debug','release'):
        binary=project/mode
        subprocess.run([DYN,'build',str(project),'--'+mode,'--no-cache','--quiet','--output',str(binary)],check=True,timeout=120)
        subprocess.run([str(binary)],check=True,timeout=20)
print('PASS fallible arena handles, defaults, bounded rollback and uninitialized reuse')
