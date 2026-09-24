#!/usr/bin/env python3
"""Check bounded codecs against Python's standard codecs with deterministic inputs."""
import base64
import os
from pathlib import Path
import random
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
dyn = str(Path(os.environ.get('DYN', root / 'build/dyn')).resolve())
source = '''use "std/encoding/hex"
use "std/encoding/base32"
use "std/encoding/base64"
use "std/bytes"
fn verify(raw: []const u8, h: []const u8, b32: []const u8, b64: []const u8) {
  encoded: [512]u8 = [] decoded: [256]u8 = []
  hx := hex.encode(encoded[..], raw, false)
  if !hx.ok || !bytes.equal(hx.data, h) || !hex.decode(decoded[..], h).ok || !bytes.equal(decoded[..#len(raw)], raw) { #panic("hex reference") }
  b := base32.encode(encoded[..], raw)
  if !b.ok || !bytes.equal(b.data, b32) { #panic("base32 reference") }
  c := base32.decode(decoded[..#len(raw)], b32)
  if !c.ok || !bytes.equal(c.data, raw) { #panic("base32 reference decode exact fit") }
  d := base64.encode(encoded[..], raw)
  if !d.ok || !bytes.equal(d.data, b64) { #panic("base64 reference") }
  e := base64.decode(decoded[..#len(raw)], b64)
  if !e.ok || !bytes.equal(e.data, raw) { #panic("base64 reference decode exact fit") }
  if #len(raw) > 0 {
    for *byte in decoded { byte.* = 99 }
    if hex.decode(decoded[..#len(raw)-1], h).error != hex.ErrorKind.Capacity ||
       base32.decode(decoded[..#len(raw)-1], b32).error != base32.ErrorKind.Capacity ||
       base64.decode(decoded[..#len(raw)-1], b64).error != base64.ErrorKind.Capacity { #panic("codec capacity result") }
    for checked_byte in decoded { if checked_byte != 99 { #panic("capacity changed output") } }
  }
}
fn main() {
'''
rng = random.Random(971)
for index, length in enumerate([*range(66), 127, 128, 255]):
    raw = rng.randbytes(length)
    initializer = ','.join(str(byte) for byte in raw)
    source += f'raw{index}: [{length}]u8 = [{initializer}]\n'
    source += (f'verify(raw{index}[..], "{raw.hex()}", '
               f'"{base64.b32encode(raw).decode()}", "{base64.b64encode(raw).decode()}")\n')
source += '}\n'
with tempfile.TemporaryDirectory(prefix='dyn-codec-contracts-') as directory:
    path = Path(directory)
    (path / 'main.dyn').write_text(source)
    for mode in ([], ['--release']):
        subprocess.run([dyn, 'build', str(path), '--quiet', '--no-cache', '--output', str(path / 'program'), *mode], cwd=root, check=True)
        subprocess.run([str(path / 'program')], cwd=root, check=True, timeout=30)
print('69 codec reference cases passed in debug/release')
