#!/usr/bin/env python3
"""Filesystem identity, destination preservation and bounded arena read contracts."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-fs-') as directory:
    root=Path(directory);source=root/'source';alias=root/'alias';target=root/'target'
    source.write_bytes(b'keep me');os.link(source,alias);target.write_bytes(b'keep target')
    text='''use "std/fs" fs
use "std/mem" mem
use "std/bytes" bytes
fn main() {
  scratch: [32]u8 = []
'''
    text+=f'if fs.copy_file({json.dumps(str(source))}, {json.dumps(str(alias))}, scratch[..]).ok {{ #panic("hard link copy") }}\n'
    text+=f'if fs.copy_file({json.dumps(str(source))}, {json.dumps(str(target))}, scratch[..0]).ok {{ #panic("empty scratch copy") }}\n'
    text+='backing: [7]u8 = []\narena := mem.arena_from_buffer(backing[..])\n'
    text+=f'loaded := fs.read_all(&arena, {json.dumps(str(source))}, 7)\n'
    text+='if !loaded.ok || !bytes.equal(loaded.data, "keep me") || mem.arena_used(&arena) != 7 { #panic("exact-fit read") }\nmem.arena_reset(&arena)\n'
    text+=f'oversized := fs.read_all(&arena, {json.dumps(str(source))}, 6)\n'
    text+='if oversized.ok || mem.arena_used(&arena) != 0 { #panic("read rollback") }\n}\n'
    (root/'main.dyn').write_text(text)
    for mode in ([],['--release']):
        subprocess.run([DYN,'build',str(root),'--quiet','--no-cache','--output',str(root/'run'),*mode],cwd=ROOT,check=True)
        subprocess.run([str(root/'run')],check=True,timeout=10)
        assert source.read_bytes()==alias.read_bytes()==b'keep me'
        assert target.read_bytes()==b'keep target'
print('PASS hard links, empty scratch preserves destination, exact-fit read and arena rollback')
