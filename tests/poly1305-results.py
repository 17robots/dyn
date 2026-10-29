#!/usr/bin/env python3
"""RFC 8439 Poly1305 and independent integer oracle."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
import random
SOURCE=r'''use "std/crypto/poly1305" poly
fn check(ok: bool) { if !ok { #panic("Poly1305 contract") } }
fn vector(key: []const u8, message: []const u8, expected: []const u8) {
 tag := poly.authenticate(message,key)
 check(tag.ok && poly.equal(tag.value[..],expected))
 for i in 0..16 {
  changed := tag.value
  changed[i] ^= 1
  check(!poly.equal(changed[..],expected))
 }
 check(!poly.equal(tag.value[..15],expected) && !poly.equal(tag.value[..],expected[..15]))
 byte_state := poly.init(key)
 for i in 0..#len(message) {
  check(poly.update(&byte_state,""))
  check(poly.update(&byte_state,message[i..i+1]))
 }
 bytewise := poly.finish(&byte_state)
 check(bytewise.ok && poly.equal(bytewise.value[..],expected))
 for split in 0..#len(message)+1 {
  state := poly.init(key)
  check(poly.update(&state,message[..split]))
  check(poly.update(&state,message[split..]))
  streamed := poly.finish(&state)
  check(streamed.ok && poly.equal(streamed.value[..],expected))
  check(!poly.finish(&state).ok && !poly.update(&state,""))
 }
}
fn main() {
 check(!poly.init("bad").ok && !poly.authenticate("","").ok)
'''

def oracle(key,message):
    r=int.from_bytes(key[:16],'little') & 0x0ffffffc0ffffffc0ffffffc0fffffff
    h=0
    for i in range(0,len(message),16):
        h=(h+int.from_bytes(message[i:i+16]+b'\x01','little'))*r%((1<<130)-5)
    return ((h+int.from_bytes(key[16:],'little'))% (1<<128)).to_bytes(16,'little')
def literal(value): return '"'+''.join('\\x%02x'%b for b in value)+'"'
rng=random.Random(8439)
vectors=[(bytes.fromhex('85d6be7857556d337f4452fe42d506a80103808afb0db2fd4abff6af4149f51b'),b'Cryptographic Forum Research Group')]
assert oracle(*vectors[0]).hex()=='a8061dc1305136c6c22b8baf0c0127a9'
for length in list(range(67))+[127,128,129,255,256,257,511,512,513]:
    vectors.append((rng.randbytes(32),rng.randbytes(length)))
    vectors.append((b'\xff'*32,b'\xff'*length))
# r=1 makes two block sums hit the reduction boundary exactly.
for a,b in ((3,3),(2,3),(2,2)):
    vectors.append((b'\x01'+b'\x00'*15+b'\xff'*16,((1<<128)-a).to_bytes(16,'little')+((1<<128)-b).to_bytes(16,'little')))
for length in (0,1,16,17,128):vectors.append((b'\x00'*16+bytes(range(16)),b'\xff'*length))
for key,message in vectors:
    SOURCE+=' vector('+literal(key)+','+literal(message)+','+literal(oracle(key,message))+')\n'
SOURCE+='}\n'
with tempfile.TemporaryDirectory(prefix='dyn-poly1305-') as directory:
    work=Path(directory);(work/'main.dyn').write_text(SOURCE)
    for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
        output=work/'program'
        subprocess.run([DYN,'build',str(work),*flags,'--quiet','--no-cache','--output',str(output)],check=True,timeout=300)
        subprocess.run([str(output)],check=True,timeout=30)
    for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows','wasm32-wasi'):
        output=work/target
        subprocess.run([DYN,'build',str(work),'--target',target,'--release','--quiet','--output',str(output)],check=True,timeout=300)
        emulator={'aarch64-linux':'qemu-aarch64','riscv64-linux':'qemu-riscv64','x86_64-windows':'wine'}.get(target)
        if emulator and shutil.which(emulator): subprocess.run([emulator,str(output)],check=True,timeout=60)
        if target=='wasm32-wasi' and shutil.which('node'):
            script="const {WASI}=require('node:wasi'),fs=require('fs');(async()=>{const wasi=new WASI({version:'preview1',returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});"
            subprocess.run(['node','--no-warnings','-e',script,str(output)],check=True,timeout=60)
print('PASS Poly1305: RFC8439, integer oracle, streaming splits and cross-targets')
