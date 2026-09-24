#!/usr/bin/env python3
"""Independent stored/fixed/dynamic references, every prefix, corruption and capacity."""
import gzip
import os
from pathlib import Path
import random
import subprocess
import tempfile
import zlib
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())
source = '''use "std/compress/deflate" d
use "std/bytes" bytes
fn verify(raw: []const u8, encoded: []const u8, zipped: []const u8) {
  output: [4096]u8 = []
  state := d.InflateState{}
  at: usize = 0
  for at <= #len(encoded) {
    result := d.resume(&state, output[..], encoded[..at])
    if state.error != 0 || result.written > #len(raw) || !bytes.equal(output[..result.written], raw[..result.written]) { #panic("incremental deflate prefix") }
    if at == #len(encoded) && (!result.ok || !bytes.equal(output[..result.written], raw)) { #panic("deflate complete") }
    at += 1
  }
  gzip_state := d.GzipState{}
  at = 0
  for at <= #len(zipped) {
    gzip_result := d.resume_gzip(&gzip_state, output[..], zipped[..at])
    if gzip_state.error != 0 || gzip_result.written > #len(raw) || !bytes.equal(output[..gzip_result.written], raw[..gzip_result.written]) { #panic("incremental gzip prefix") }
    if gzip_result.ok != (at == #len(zipped)) { #panic("gzip terminal framing") }
    at += 1
  }
  if #len(raw) > 0 && d.inflate(output[..#len(raw)-1], encoded).ok { #panic("deflate capacity") }
  damaged: [8192]u8 = []
  at = 0 for at < #len(zipped) { damaged[at] = zipped[at] at += 1 }
  damaged[#len(zipped)-8] ^= 1
  if d.gunzip_internal(output[..], damaged[..#len(zipped)]).ok { #panic("gzip CRC") }
}
fn main() {
'''
rng = random.Random(451)
for i, raw in enumerate([b'', b'x', b'hello '*100, bytes(range(256))*4, rng.randbytes(1024)]):
    for j, (level, strategy) in enumerate([(0,zlib.Z_DEFAULT_STRATEGY),(6,zlib.Z_FIXED),(9,zlib.Z_DEFAULT_STRATEGY)]):
        c=zlib.compressobj(level,zlib.DEFLATED,-15,8,strategy)
        encoded=c.compress(raw)+c.flush()
        zipped=gzip.compress(raw,mtime=0)
        # Optional filename exercises incremental header scanning.
        zipped=zipped[:3]+bytes([zipped[3]|8])+zipped[4:10]+b'long-name.txt\0'+zipped[10:]
        names=[]
        for key, data in [('raw',raw),('encoded',encoded),('zipped',zipped)]:
            name=f'{key}{i}_{j}';names.append(name)
            source+=f'{name}: [{len(data)}]u8 = [{",".join(map(str,data))}]\n'
        source+=f'verify({names[0]}[..], {names[1]}[..], {names[2]}[..])\n'
source+='}\n'
with tempfile.TemporaryDirectory(prefix='dyn-compression-') as directory:
    path=Path(directory);(path/'main.dyn').write_text(source)
    for mode in ([],['--release']):
        subprocess.run([DYN,'build',str(path),'--quiet','--no-cache','--output',str(path/'run'),*mode],cwd=ROOT,check=True)
        subprocess.run([str(path/'run')],cwd=ROOT,check=True,timeout=60)
print('PASS 15 compression reference cases at every input prefix, debug/release')
