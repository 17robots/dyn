#!/usr/bin/env python3
"""Arena producer preflight preserves overlapping immutable inputs."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use "std/archive/zip" zip
use "std/unicode/text" text
use "std/mem" mem
use "std/hash" hashing
use "std/bytes" bytes
use "std/errors" errors
fn main() {
  buffer:[4+mem.ArenaBufferOverhead]u8=[]
  pad:=(16-(#cast(usize,&buffer[0])&15))&15
  arena:=mem.arena_from_buffer(buffer[pad..pad+mem.ArenaHeader+4])
  _=mem.push_bytes_uninit(arena,1)
  payload:=arena.data[mem.ArenaHeader..]
  _=mem.copy(payload,"abc")
  mark:=mem.arena_mark(arena)
  entry:=zip.Entry{payload:payload[..3],compressed_size:3,uncompressed_size:3,checksum:hashing.crc32(payload[..3])}
  result:=zip.extract(arena,entry)
  if result.ok || result.kind!=errors.Kind.InvalidInput || result.detail!=zip.ErrorKind.Overlap || result.error!=0 || #len(result.value)!=0 || mem.arena_mark(arena)!=mark || !bytes.equal(payload[..3],"abc") { #panic("ZIP overlap preflight") }
  backing:[1024+mem.ArenaBufferOverhead]u8=[]
  unicodearena:=mem.arena_from_buffer(backing[..])
  text_payload:=unicodearena.data[mem.ArenaHeader..]
  text_payload[0]='a'
  converted:=text.normalize(unicodearena,text_payload[..1],text.Form.NFC)
  if converted.ok || mem.arena_mark(unicodearena)!=mem.arena_start(unicodearena) || text_payload[0]!='a' { #panic("normalization work overlap") }
  text_payload[144]='A'
  converted=text.normalize(unicodearena,text_payload[144..145],text.Form.NFC)
  if converted.ok || mem.arena_mark(unicodearena)!=mem.arena_start(unicodearena) || text_payload[144]!='A' { #panic("normalization output overlap") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-producer-overlap-') as directory:
    work=Path(directory);(work/'main.dyn').write_text(SOURCE)
    for mode in ('debug','release'):
        subprocess.run([DYN,'build',str(work),'--'+mode,'--quiet','--no-cache','--output',str(work/'test')],check=True,timeout=120)
        subprocess.run([str(work/'test')],check=True,timeout=10)
        print('PASS producer overlap preflight '+mode,flush=True)
