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
source='''use "std/encoding/base32" codec
use "std/encoding" encoding
use "std/mem" mem
use "std/errors" errors
use "std/bytes" bytes
fn good(raw,encoded:[]const u8) {
  backing:[2048]u8 mem.fill(backing[..],99)
  arena:=mem.arena_from_buffer(backing[..])
  _=mem.push_bytes_uninit(&arena,7)
  decoded:=codec.decode(&arena,encoded)
  if !decoded.ok || decoded.kind!=errors.Kind.None || decoded.error!=0 || decoded.offset!=0 || decoded.detail!=encoding.ErrorKind.None || !bytes.equal(decoded.value,raw) || mem.arena_mark(&arena)!=7+#len(raw) { #panic("base32 oracle") }
  if !bytes.equal(codec.encode(&arena,raw),encoded) { #panic("base32 encode") }
}
fn bad(encoded:[]const u8,offset:usize) {
  backing:[256]u8 mem.fill(backing[..],99)
  arena:=mem.arena_from_buffer(backing[..])
  prefix:=mem.push_bytes_uninit(&arena,7) prefix[0]=91
  arena.poison_on_rewind=true
  decoded:=codec.decode(&arena,encoded)
  if decoded.ok || decoded.kind!=errors.Kind.InvalidInput || decoded.error!=0 || decoded.offset!=offset || decoded.detail!=encoding.ErrorKind.InvalidInput || #len(decoded.value)!=0 || mem.arena_mark(&arena)!=7 || prefix[0]!=91 || backing[7]!=99 { #panic("base32 failure preflight") }
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
source+='''
  backing:[8]u8=['M','Z','X','W','6','Y','T','B']
  arena:=mem.arena_from_buffer(backing[1..6])
  overlap:=codec.decode(&arena,backing[..])
  if overlap.ok || overlap.detail!=encoding.ErrorKind.Overlap || overlap.kind!=errors.Kind.InvalidInput || overlap.error!=0 || mem.arena_mark(&arena)!=0 || !bytes.equal(backing[..],"MZXW6YTB") { #panic("base32 overlap") }
  zero:codec.Decoded
  if zero.ok || zero.kind!=errors.Kind.None || zero.error!=0 || zero.offset!=0 || #len(zero.value)!=0 { #panic("base32 zero") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-base32-results-') as directory:
    work=Path(directory)
    for mode in ('debug','release'):
        (work/'main.dyn').write_text(source)
        subprocess.run([DYN,'build',str(work),'--'+mode,'--quiet','--no-cache','--output',str(work/'test')],check=True,timeout=120)
        subprocess.run([str(work/'test')],check=True,timeout=10)
        print('PASS base32 results, 66 Python oracles, offsets, rollback, overlap '+mode,flush=True)
