#!/usr/bin/env python3
"""RFC5869, PBKDF2 and HMAC guard/alias regression proofs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
import hashlib
import hmac
SOURCE=r'''use "std/crypto/hmac" hmac
use "std/crypto/kdf" kdf
use "std/crypto/password" password
use "std/crypto/chacha20" chacha
use "std/bytes" bytes
fn check(ok: bool) { if !ok { #panic("KDF contract") } }
fn filled(data: []const u8, value: u8) bool { for byte in data { if byte != value { return false } }
 return true }
fn main() {
 output: [100]u8 = []
 scratch: [100]u8 = []
 key: [32]u8 = []
 for i in 0..32 { key[i] = #cast(u8,i) }
'''

def literal(b): return '"'+''.join('\\x%02x'%x for x in b)+'"'
key=bytes(range(32))
mac=hmac.digest(key,b'message','sha256')
prk=hmac.digest(b'salt',key,'sha256')
t=b'';result=b''
for counter in range(1,4):
 t=hmac.digest(prk,t+b'info'+bytes([counter]),'sha256');result+=t
SOURCE+=' check(bytes.equal(hmac.sha256(output[..],key[..],"message"),'+literal(mac)+'))\n'
SOURCE+=' check(kdf.hkdf(output[..96],"salt",key[..],"info",scratch[..]) && bytes.equal(output[..96],'+literal(result)+'))\n'
SOURCE+=' check(password.pbkdf2_sha256(output[..96],"password","salt",2,scratch[..]) && bytes.equal(output[..96],'+literal(hashlib.pbkdf2_hmac('sha256',b'password',b'salt',2,96))+'))\n'
SOURCE+=r''' for i in 0..100 { output[i] = 165 }
 check(!kdf.hkdf_expand(output[..64],output[..32],"info",scratch[..]) && filled(output[..],165))
 check(!kdf.hkdf_expand(output[..64],key[..],output[63..64],scratch[..]) && filled(output[..],165))
 check(!kdf.hkdf_expand(output[..64],key[..],"info",output[63..]) && filled(output[..],165))
 check(!kdf.hkdf_expand(output[..64],key[..],scratch[..4],scratch[..]))
 check(!kdf.hkdf_expand(output[..64],scratch[..32],"info",scratch[..]))
 check(!password.pbkdf2_sha256(output[..64],output[..32],"salt",2,scratch[..]) && filled(output[..],165))
 check(!password.pbkdf2_sha256(output[..64],"password",output[63..64],2,scratch[..]) && filled(output[..],165))
 check(!password.pbkdf2_sha256(output[..64],"password","salt",2,output[63..]) && filled(output[..],165))
 check(!password.pbkdf2_sha256(output[..64],"password",scratch[..4],2,scratch[..]))
 check(!password.pbkdf2_sha256(output[..64],scratch[..8],"salt",2,scratch[..]))
 huge := (&key[0])[..~#cast(usize,0)]
 check(!kdf.hkdf_expand(output[..64],key[..],huge,scratch[..]) && filled(output[..],165))
 check(!password.pbkdf2_sha256(output[..64],"password",huge,2,scratch[..]) && filled(output[..],165))
 // Raw ChaCha counter exhaustion must reject before reading a forged span.
 before := key
 check(!chacha.xor(huge,huge,key[..],key[..12],0xffffffff) && bytes.equal(key[..],before[..]))
 if #sizeof(usize) == 8 {
  size: u64 = 2305843009213693952
  huge_key := (&key[0])[..#cast(usize,size)]
  check(#len(hmac.sha256(output[..],huge_key,"message")) == 0 && filled(output[..],165))
 }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-kdf-') as directory:
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
print('PASS KDF: independent HMAC/HKDF/PBKDF2 vectors, alias preservation and checked limits')
