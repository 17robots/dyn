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
  buffer:[16]u8=[]
  buffer[0]='a'
  buffer[1]='b'
  buffer[2]='c'
  arena:=mem.arena_from_buffer(buffer[1..4])
  entry:=zip.Entry{payload:buffer[..3],compressed_size:3,uncompressed_size:3,checksum:hashing.crc32(buffer[..3])}
  result:=zip.extract(&arena,entry)
  if result.ok || result.kind!=errors.Kind.InvalidInput || result.detail!=zip.ErrorKind.Overlap || result.error!=0 || #len(result.value)!=0 || mem.arena_mark(&arena)!=0 || !bytes.equal(buffer[..3],"abc") { #panic("ZIP overlap preflight") }
  backing:[1024]u8=[]
  backing[0]='a'
  unicodearena:=mem.arena_from_buffer(backing[..])
  converted:=text.normalize(&unicodearena,backing[..1],text.Form.NFC)
  if converted.ok || mem.arena_mark(&unicodearena)!=0 || backing[0]!='a' { #panic("normalization work overlap") }
  backing[144]='A'
  converted=text.normalize(&unicodearena,backing[144..145],text.Form.NFC)
  if converted.ok || mem.arena_mark(&unicodearena)!=0 || backing[144]!='A' { #panic("normalization output overlap") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-producer-overlap-') as directory:
    work=Path(directory);(work/'main.dyn').write_text(SOURCE)
    for mode in ('debug','release'):
        subprocess.run([DYN,'build',str(work),'--'+mode,'--quiet','--no-cache','--output',str(work/'test')],check=True,timeout=120)
        subprocess.run([str(work/'test')],check=True,timeout=10)
        print('PASS producer overlap preflight '+mode,flush=True)
