#!/usr/bin/env python3
"""RFC6979 P-256/SHA256 vector plus independent Python integer oracle."""
import hashlib,hmac,os,random,shutil,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
P=2**256-2**224+2**192+2**96-1
N=0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
G=(0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)
def point_add(a,b):
 if a is None:return b
 if b is None:return a
 x,y=a;u,v=b
 if x==u:
  if (y+v)%P==0:return None
  slope=(3*x*x-3)*pow(2*y,-1,P)%P
 else:slope=(v-y)*pow(u-x,-1,P)%P
 xx=(slope*slope-x-u)%P
 return xx,(slope*(x-xx)-y)%P
def scalar(k,p=G):
 result=None
 while k:
  if k&1:result=point_add(result,p)
  p=point_add(p,p);k>>=1
 return result
def nonce(key,digest):
 key_bytes=key.to_bytes(32,'big');h=(int.from_bytes(digest,'big')%N).to_bytes(32,'big')
 k=b'\0'*32;v=b'\1'*32
 def mac(k,m):return hmac.new(k,m,hashlib.sha256).digest()
 k=mac(k,v+b'\0'+key_bytes+h);v=mac(k,v)
 k=mac(k,v+b'\1'+key_bytes+h);v=mac(k,v)
 while True:
  v=mac(k,v);candidate=int.from_bytes(v,'big')
  if 0<candidate<N:return candidate
  k=mac(k,v+b'\0');v=mac(k,v)
def vector(key,message):
 digest=hashlib.sha256(message).digest();k=nonce(key,digest)
 r=scalar(k)[0]%N;s=pow(k,-1,N)*(int.from_bytes(digest,'big')+r*key)%N
 public=scalar(key)
 return b'\4'+b''.join(x.to_bytes(32,'big') for x in public),r.to_bytes(32,'big')+s.to_bytes(32,'big')
def literal(value):return '"'+''.join('\\x%02x'%b for b in value)+'"'
s='''use "std/crypto/signature" facade
use "std/errors" errors
use "std/crypto/p256" p
use "std/bytes" bytes
fn check(ok: bool) { if !ok { #panic("P256 contract") } }
fn vector(key: []const u8,message: []const u8,expected_public: []const u8,expected_signature: []const u8) {
 public: [73]u8
 signature: [72]u8
 for i in 0..73 { public[i]=165 }
 for i in 0..72 { signature[i]=165 }
 check(facade.p256_public(public[..],key).ok && bytes.equal(public[..65],expected_public))
 check(facade.p256_sign(signature[..],message,key).ok && bytes.equal(signature[..64],expected_signature))
 check(p.valid_public_key(public[..65]))
 check(facade.p256_verify(signature[..64],message,public[..65]))
 for i in 65..73 { check(public[i]==165) }
 for i in 64..72 { check(signature[i]==165) }
 signature[0]^=1
 check(!p.verify(signature[..64],message,public[..65]))
 signature[0]^=1
 signature[32]^=1
 check(!p.verify(signature[..64],message,public[..65]))
 public[1]^=1
 check(!p.valid_public_key(public[..65]))
 check(!p.verify(expected_signature,message,public[..65]))
}
fn main() {
'''
key=int('c9afa9d845ba75166b5c215767b1d6934e50c3db36e89b127b8a622b120f6721',16)
assert vector(key,b'sample')[1].hex()=='efd48b2aacb6a8fd1140dd9cd45e81d69d2c877b56aaf991c34d0ea84eaf3716f7cb1c942d657c41d436c7a1b6e29f65f3e900dbb9aff4064dc4ab2f843acda8'
rng=random.Random(6979)
vectors=[(key,b'sample'),(1,b''),(N-1,b'boundary'),(rng.randrange(1,N),rng.randbytes(257))]
for key,message in vectors:
 public,signature=vector(key,message)
 s+=' vector('+','.join(map(literal,(key.to_bytes(32,'big'),message,public,signature)))+')\n'
# Force equal and opposite points in the final verification addition.
r=scalar(2)[0]%N
base=b'\4'+b''.join(x.to_bytes(32,'big') for x in G)
raw=r.to_bytes(32,'big')
s+=' check(p.verify_hash('+literal(raw+raw)+','+literal(raw)+','+literal(base)+'))\n'
s+=' check(!p.verify_hash('+literal(raw+(1).to_bytes(32,'big'))+','+literal((N-r).to_bytes(32,'big'))+','+literal(base)+'))\n'
# Noncanonical scalar encodings reject before group work.
s+=' check(!p.verify('+literal(N.to_bytes(32,'big')+b'\1'*32)+',"",'+literal(b'\4'+b'\0'*64)+'))\n'
s+=' check(!p.verify('+literal(b'\1'*32+N.to_bytes(32,'big'))+',"",'+literal(b'\4'+b'\0'*64)+'))\n'
s+=''' key: [32]u8
 output: [96]u8
 signature: [64]u8
 public: [65]u8
 for i in 0..96 { output[i]=165 }
 invalid:=facade.p256_public(output[..],key[..])
 check(!invalid.ok && invalid.kind==errors.Kind.InvalidInput && #len(invalid.value)==0 && invalid.provider_code==0)
 check(!facade.p256_sign(output[..],"",key[..]).ok)
 for i in 0..96 { check(output[i]==165) }
 check(!p.public_key(output[..],key[..]) && !p.sign(output[..],"",key[..]))
 key[31]=1
 check(!p.public_key(output[..64],key[..]))
 check(!facade.p256_public(output[..],output[64..96]).ok)
 check(!p.public_key(output[..],output[64..96]))
 check(!facade.p256_sign(output[..],output[80..81],key[..]).ok)
 check(!p.sign(output[..],output[80..81],key[..]))
 check(!p.valid_public_key(public[..]) && !p.valid_public_key(public[..64]))
 check(!p.verify(signature[..],"",public[..]))
 check(!p.verify(signature[..63],"",public[..]))
}\n'''
with tempfile.TemporaryDirectory(prefix='dyn-p256-') as directory:
 work=Path(directory);(work/'main.dyn').write_text(s)
 for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
  output=work/'program'
  subprocess.run([DYN,'build',str(work),*flags,'--quiet','--no-cache','--output',str(output)],check=True,timeout=300)
  subprocess.run([str(output)],check=True,timeout=120)
 for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows','wasm32-wasi'):
  output=work/target
  subprocess.run([DYN,'build',str(work),'--target',target,'--release','--quiet','--no-cache','--output',str(output)],check=True,timeout=300)
  emulator={'aarch64-linux':'qemu-aarch64','riscv64-linux':'qemu-riscv64','x86_64-windows':'wine'}.get(target)
  if emulator and shutil.which(emulator):subprocess.run([emulator,str(output)],check=True,timeout=240)
  if target=='wasm32-wasi' and shutil.which('node'):
   script="const {WASI}=require('node:wasi'),fs=require('fs');(async()=>{const wasi=new WASI({version:'preview1',returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});"
   subprocess.run(['node','--no-warnings','-e',script,str(output)],check=True,timeout=240)
print('PASS native P256: RFC6979, independent integer oracle, signing/verification, cross-targets')
