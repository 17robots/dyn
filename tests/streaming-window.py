#!/usr/bin/env python3
"""Independent zlib/gzip references far larger than the decoder's fixed buffers."""
import gzip
import os
from pathlib import Path
import random
import subprocess
import tempfile
import zlib
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())
SOURCE = '''use "std/compress/deflate" d
use "std/compress/gzip" gz
use "std/io" io
use "std/fs" fs
use "std/mem" mem
use "std/bytes" bytes
struct Input { source: []const u8, at: usize, chunk: usize }
fn read(data: rawptr, out: []u8) io.Result {
  state := #cast(*Input) data
  amount := #len(out)
  if amount > state.chunk { amount = state.chunk }
  if amount > #len(state.source) - state.at { amount = #len(state.source) - state.at }
  _ = mem.copy(out[..amount], state.source[state.at..state.at + amount]) state.at += amount
  status := io.Status.Complete if state.at == #len(state.source) { status = io.Status.End }
  return io.Result{ transferred: amount, status: status }
}
fn verify(raw: []const u8, encoded: []const u8, gzip: bool, chunk: usize, corrupt: bool) {
  input := Input{ source: encoded, chunk: chunk }
  reader := io.Reader{ data: #cast(rawptr) &input, read: &read }
  compressed: [1024]u8 = [] history: [33026]u8 = [] output: [503]u8 = []
  state := d.decoder(reader, compressed[..], history[..])
  state.gzip = gzip
  decoded := d.decoder_reader(&state)
  at: usize = 0
  for {
    result := io.read(decoded, output[..])
    if result.status == io.Status.Error {
      if !corrupt || result.error != -74 { #panic("stream error") }
      again := io.read(decoded, output[..])
      if again.status != io.Status.Error || again.error != result.error { #panic("sticky error") }
      return
    }
    if result.transferred > #len(raw) - at || !bytes.equal(output[..result.transferred], raw[at..at + result.transferred]) { #panic("stream bytes") }
    at += result.transferred
    if result.status == io.Status.End {
      if corrupt || at != #len(raw) { #panic("stream completion") }
      if io.read(decoded, output[..]).status != io.Status.End { #panic("sticky end") }
      return
    }
    if result.transferred == 0 { #panic("stalled decoder") }
  }
}
fn main() {
  storage: [2000000]u8 = [] arena := mem.arena_from_buffer(storage[..])
BODY
}
'''
rng = random.Random(1952)
raw = rng.randbytes(40000) + (b'abcd' * 20000) + bytes(range(256)) * 200
# Include long-distance matches across output/input refill boundaries.
raw += raw[-32768:] * 2
with tempfile.TemporaryDirectory(prefix='dyn-window-') as tmp:
    directory = Path(tmp)
    (directory / 'raw').write_bytes(raw)
    body = f'r := fs.read_all(&arena, "{directory}/raw", 1000000)\nif !r.ok {{ #panic("raw read") }}\n'
    cases = []
    for level, strategy in [(0, zlib.Z_DEFAULT_STRATEGY), (6,zlib.Z_FIXED), (9,zlib.Z_DEFAULT_STRATEGY)]:
        c = zlib.compressobj(level,zlib.DEFLATED,-15,8,strategy)
        cases.append((c.compress(raw)+c.flush(),False,False))
    zipped = gzip.compress(raw,mtime=0)
    header = zipped[:3] + b'\x1e' + zipped[4:10] + b'\x00\x10' + b'E'*4096 + b'N'*4096+b'\0comment\0'
    header += (zlib.crc32(header)&65535).to_bytes(2,'little')
    cases.append((header+zipped[10:],True,False))
    cases.append((gzip.compress(raw[:100000],mtime=0)+gzip.compress(raw[100000:],mtime=0),True,False))
    cases.append((zipped[:-8]+bytes([zipped[-8]^1])+zipped[-7:],True,True))
    cases.append((zipped[:-1],True,True))
    cases.append((zipped+b'x',True,True))
    cases.append((header[:-1]+bytes([header[-1]^1])+zipped[10:],True,True))
    for i,(encoded,gz,bad) in enumerate(cases):
        (directory / f'encoded{i}').write_bytes(encoded)
        body += f'mark{i} := mem.arena_mark(&arena)\ne{i} := fs.read_all(&arena, "{directory}/encoded{i}", 1000000)\nif !e{i}.ok {{ #panic("encoded read") }}\n'
        for chunk in [1, 79, 65536]:
            body += f'verify(r.data, e{i}.data, {str(gz).lower()}, {chunk}, {str(bad).lower()})\n'
        body += f'mem.arena_rewind(&arena, mark{i})\n'
    (directory / 'main.dyn').write_text(SOURCE.replace('BODY',body))
    for mode in [[],['--release']]:
        subprocess.run([DYN,'build',str(directory),'--quiet','--no-cache','--output',str(directory/'run'),*mode],cwd=ROOT,check=True)
        subprocess.run([str(directory/'run')],cwd=ROOT,check=True,timeout=90)
print('PASS bounded streaming: 9 references × 3 input splits × debug/release')
