#!/usr/bin/env python3
"""Base32 portable parser results and preflight against Python byte oracles."""
import base64
import os
from pathlib import Path
import random
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
def literal(data): return '"'+''.join('\\x%02x'%b for b in data)+'"'
source='''use parse "std/parse"
use codec "std/encoding/base32"
use mem "std/mem"
use bytes "std/bytes"
fn good(raw,encoded:[]const u8) {
  backing:[2048 + mem.ArenaBufferOverhead]u8
  mem.fill(backing[..],99)
  arena:=mem.arena_from_buffer(backing[..])
  _=mem.push_bytes(arena,7)
  decoded:=codec.decode(arena,encoded) catch { #panic("base32 oracle") }
  if !bytes.equal(decoded,raw) || mem.arena_mark(arena)!=mem.ArenaHeader+7+raw.len { #panic("base32 oracle") }
  if !bytes.equal(codec.encode(arena,raw),encoded) { #panic("base32 encode") }
}
fn bad(encoded:[]const u8,offset:usize) {
  backing:[256 + mem.ArenaBufferOverhead]u8
  mem.fill(backing[..],99)
  arena:=mem.arena_from_buffer(backing[..])
  prefix:=mem.push_bytes(arena,7)
  prefix[0]=91
  arena.poison_on_rewind=true
  at:usize=0
  _=codec.decode(arena,encoded) catch err {
    case err {
      .Invalid(where) => { at = where }
      _ => { #panic("base32 failure kind") }
    }
    check_failure(arena,prefix,at,offset)
    return
  }
  #panic("base32 accepted bad input")
}
fn check_failure(arena:*mem.Arena,prefix:[]u8,at:usize,offset:usize) {
  if at!=offset || mem.arena_mark(arena)!=mem.ArenaHeader+7 || prefix[0]!=91 || arena.data[mem.ArenaHeader+7]!=99 { #panic("base32 failure preflight") }
}
fn main() {
'''
rng=random.Random(32)
for n in range(66):
    raw=rng.randbytes(n)
    source+=f'good({literal(raw)},{literal(base64.b32encode(raw))})\n'
for raw,at in [(b'M',1),(b'MY',2),(b'========',0),(b'M!======',1),(b'MZ======',1),(b'MY=====A',7),(b'MY======MZXW6YTB',2)]:
    source+=f'bad({literal(raw)},{at})\n'
for at in range(8):
    raw=bytearray(b'MZXW6YTB');raw[at]=255
    source+=f'bad({literal(raw)},{at})\n'
source+='}\n'
# Input in the arena's free space is a caller bug: decode panics.
OVERLAP='''use codec "std/encoding/base32"
use mem "std/mem"
fn main() {
  backing:[8 + mem.ArenaBufferOverhead]u8
  arena:=mem.arena_from_buffer(backing[..])
  payload:=arena.data[mem.ArenaHeader..]
  _=mem.copy(payload,"MZXW6YTB")
  _=codec.decode(arena,payload[..8]) catch { return }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-base32-results-') as directory:
    work=Path(directory)
    for mode in ('debug','release'):
        (work/'main.dyn').write_text(source)
        subprocess.run([DYN,'build',str(work),'--'+mode,'--quiet','--no-cache','--output',str(work/'test')],check=True,timeout=120)
        subprocess.run([str(work/'test')],check=True,timeout=10)
        (work/'main.dyn').write_text(OVERLAP)
        subprocess.run([DYN,'build',str(work),'--'+mode,'--quiet','--no-cache','--output',str(work/'overlap')],check=True,timeout=120)
        result=subprocess.run([str(work/'overlap')],capture_output=True,timeout=10)
        assert result.returncode!=0 and b'overlaps arena output' in result.stderr, result
        print('PASS base32 results, 66 Python oracles, offsets, rollback, overlap '+mode,flush=True)
