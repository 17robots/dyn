#!/usr/bin/env python3
"""RFC 8439 AEAD and independent ChaCha/Poly1305 oracle."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
import random
SOURCE=r'''use "std/crypto/chacha20poly1305" aead
use "std/bytes" bytes
use "std/mem" mem
fn check(ok: bool) { if !ok { #panic("native AEAD contract") } }
fn vector(key: []const u8, nonce: []const u8, aad: []const u8, message: []const u8, cipher: []const u8, expected: []const u8) {
 arena := mem.Arena{}
 defer { mem.arena_release(&arena) }
 output := mem.push_array(u8,&arena,#len(message))
 tag: [16]u8 = []
 check(aead.seal(output,tag[..],message,aad,key,nonce))
 check(bytes.equal(output,cipher) && bytes.equal(tag[..],expected))
 check(aead.open(output,output,tag[..],aad,key,nonce) && bytes.equal(output,message))
 check(aead.seal(output,tag[..],output,aad,key,nonce) && bytes.equal(output,cipher) && bytes.equal(tag[..],expected))
 wrong_key: [32]u8 = []
 for i in 0..32 { wrong_key[i] = key[i] }
 wrong_key[0] ^= 1
 mem.fill(output,165)
 check(!aead.open(output,cipher,tag[..],aad,wrong_key[..],nonce))
 for byte in output { check(byte == 165) }
 wrong_nonce: [128]u8 = []
 for i in 0..#len(nonce) { wrong_nonce[i] = nonce[i] }
 wrong_nonce[0] ^= 1
 check(!aead.open(output,cipher,tag[..],aad,key,wrong_nonce[..#len(nonce)]))
 for byte in output { check(byte == 165) }
 if #len(cipher) != 0 {
  changed := mem.push_array(u8,&arena,#len(cipher))
  for i in 0..#len(cipher) { changed[i] = cipher[i] }
  changed[0] ^= 1
  check(!aead.open(output,changed,tag[..],aad,key,nonce))
  for byte in output { check(byte == 165) }
 }
 if #len(aad) != 0 {
  changed_aad := mem.push_array(u8,&arena,#len(aad))
  for i in 0..#len(aad) { changed_aad[i] = aad[i] }
  changed_aad[0] ^= 1
  check(!aead.open(output,cipher,tag[..],changed_aad,key,nonce))
  for byte in output { check(byte == 165) }
 }
 for i in 0..16 {
  tag[i] ^= 1
  mem.fill(output,165)
  check(!aead.open(output,cipher,tag[..],aad,key,nonce))
  for byte in output { check(byte == 165) }
  tag[i] ^= 1
 }
}
fn main() {
'''

def literal(value): return '"'+''.join('\\x%02x'%b for b in value)+'"'
def poly(key,message):
    r=int.from_bytes(key[:16],'little')&0x0ffffffc0ffffffc0ffffffc0fffffff
    h=0
    for i in range(0,len(message),16):
        h=(h+int.from_bytes(message[i:i+16]+b'\x01','little'))*r%((1<<130)-5)
    return ((h+int.from_bytes(key[16:],'little'))%(1<<128)).to_bytes(16,'little')
def block(key,nonce,counter):
    import struct
    state=list(struct.unpack('<4I',b'expand 32-byte k')+struct.unpack('<8I',key)+(counter,)+struct.unpack('<3I',nonce))
    work=state[:]
    def quarter(a,b,c,d):
        for x,y,z,rotation in ((a,b,d,16),(c,d,b,12),(a,b,d,8),(c,d,b,7)):
            work[x]=(work[x]+work[y])&0xffffffff
            work[z]^=work[x]
            work[z]=((work[z]<<rotation)|(work[z]>>(32-rotation)))&0xffffffff
    for _ in range(10):
        for args in ((0,4,8,12),(1,5,9,13),(2,6,10,14),(3,7,11,15),(0,5,10,15),(1,6,11,12),(2,7,8,13),(3,4,9,14)):quarter(*args)
    return struct.pack('<16I',*((a+b)&0xffffffff for a,b in zip(state,work)))
def oracle(key,nonce,aad,message):
    cipher=b''.join(bytes(a^b for a,b in zip(message[i:i+64],block(key,nonce,i//64+1))) for i in range(0,len(message),64))
    framing=aad+b'\x00'*((-len(aad))%16)+cipher+b'\x00'*((-len(cipher))%16)+len(aad).to_bytes(8,'little')+len(cipher).to_bytes(8,'little')
    return cipher,poly(block(key,nonce,0)[:32],framing)
key=bytes(range(0x80,0xa0));nonce=bytes.fromhex('070000004041424344454647');aad=bytes.fromhex('50515253c0c1c2c3c4c5c6c7')
message=b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, sunscreen would be it."
cipher,tag=oracle(key,nonce,aad,message)
assert tag.hex()=='1ae10b594f09e26a7e902ecbd0600691'
assert cipher.hex().startswith('d31a8d34648e60db7b86afbc53ef7ec2')
vectors=[(key,nonce,aad,message)]
rng=random.Random(8439)
for length in (0,1,15,16,17,63,64,65,1024):
    for aad_length in (0,1,15,16,17):
        vectors.append((rng.randbytes(32),rng.randbytes(12),rng.randbytes(aad_length),rng.randbytes(length)))
for key,nonce,aad,message in vectors:
    cipher,tag=oracle(key,nonce,aad,message)
    SOURCE+=' vector('+','.join(map(literal,(key,nonce,aad,message,cipher,tag)))+')\n'
SOURCE+=r''' key: [32]u8 = []
 nonce: [12]u8 = []
 storage: [100]u8 = []
 tag: [16]u8 = []
 check(!aead.seal(storage[..1],tag[..],storage[1..2],"",key[..],nonce[..1]))
 check(!aead.seal(storage[..10],tag[..],storage[1..11],"",key[..],nonce[..]))
 check(!aead.seal(storage[..1],tag[..],"x",storage[..1],key[..],nonce[..]))
 check(!aead.seal(storage[..1],storage[..16],"x","",key[..],nonce[..]))
 check(!aead.seal(storage[..1],tag[..],"x","",storage[..32],nonce[..]))
 check(!aead.open(storage[..1],"x",storage[..16],"",key[..],nonce[..]))
 for byte in storage { check(byte == 0) }
 if #sizeof(usize) == 8 {
  oversize_payload: u64 = 274877906881
  huge := (&key[0])[..#cast(usize,oversize_payload)]
  check(!aead.seal(huge,tag[..],huge,"",key[..],nonce[..]))
 }

}
'''
with tempfile.TemporaryDirectory(prefix='dyn-chachapoly-') as directory:
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
print('PASS native ChaCha20-Poly1305: RFC8439, independent oracle, tampering, aliasing and cross-targets')
