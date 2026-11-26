#!/usr/bin/env python3
"""Arena producer preflight preserves overlapping immutable inputs."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use zip "std/archive/zip"
use text "std/unicode/text"
use mem "std/mem"
use hashing "std/hash"
use bytes "std/bytes"
fn extract_fails(arena: *mem.Arena, entry: zip.Entry) bool {
  _=zip.extract(arena,entry) catch { return true }
  return false
}
fn normalize_fails(arena: *mem.Arena, source: []const u8) bool {
  _=text.normalize(arena,source,text.Form.NFC) catch { return true }
  return false
}
fn main() {
  buffer:[4+mem.ArenaBufferOverhead]u8
  pad:=(16-(#cast(usize,&buffer[0])&15))&15
  arena:=mem.arena_from_buffer(buffer[pad..pad+mem.ArenaHeader+4])
  _=mem.push_bytes(arena,1)
  payload:=arena.data[mem.ArenaHeader..]
  _=mem.copy(payload,"abc")
  mark:=mem.arena_mark(arena)
  entry:=zip.Entry{payload:payload[..3],compressed_size:3,uncompressed_size:3,checksum:hashing.crc32(payload[..3])}
  if !extract_fails(arena,entry) || mem.arena_mark(arena)!=mark || !bytes.equal(payload[..3],"abc") { #panic("ZIP overlap preflight") }
  backing:[1024+mem.ArenaBufferOverhead]u8
  unicodearena:=mem.arena_from_buffer(backing[..])
  text_payload:=unicodearena.data[mem.ArenaHeader..]
  text_payload[0]='a'
  if !normalize_fails(unicodearena,text_payload[..1]) || mem.arena_mark(unicodearena)!=mem.ArenaHeader || text_payload[0]!='a' { #panic("normalization work overlap") }
  text_payload[144]='A'
  if !normalize_fails(unicodearena,text_payload[144..145]) || mem.arena_mark(unicodearena)!=mem.ArenaHeader || text_payload[144]!='A' { #panic("normalization output overlap") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-producer-overlap-') as directory:
    work=Path(directory);(work/'main.dyn').write_text(SOURCE)
    for mode in ('debug','release'):
        subprocess.run([DYN,'build',str(work),'--'+mode,'--quiet','--no-cache','--output',str(work/'test')],check=True,timeout=120)
        subprocess.run([str(work/'test')],check=True,timeout=10)
        print('PASS producer overlap preflight '+mode,flush=True)
