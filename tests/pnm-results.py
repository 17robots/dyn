#!/usr/bin/env python3
"""Portable graymap/pixmap binary and plain codecs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use "std/image/pnm" pnm
use "std/mem" mem
use "std/bytes" bytes
use "std/errors" errors
fn check(ok: bool) { if !ok { #panic("PNM contract") } }
fn main() {
 arena := mem.Arena{}
 defer { mem.arena_release(&arena) }
 decoded := pnm.decode(&arena,"P3\n# comment\n2 1\n15\n15 0 7 0 15 15\n")
 check(decoded.ok && decoded.value.info.width == 2 && decoded.value.info.height == 1 && decoded.value.info.channels == 3 && bytes.equal(decoded.value.pixels,"\xff\x00\x77\x00\xff\xff"))
 encoded := pnm.encode(&arena,decoded.value.pixels,2,1,3)
 check(encoded.ok && bytes.equal(encoded.value,"P6\n2 1\n255\n\xff\x00\x77\x00\xff\xff"))
 check(pnm.decode(&arena,encoded.value).ok)
 decoded = pnm.decode(&arena,"P5\n3 1\n65535\n\x00\x00\x80\x00\xff\xff")
 check(decoded.ok && bytes.equal(decoded.value.pixels,"\x00\x80\xff"))
 decoded = pnm.decode(&arena,"P5\n3 1\n255\n\n# ")
 check(decoded.ok && bytes.equal(decoded.value.pixels,"\n# "))
 encoded = pnm.encode(&arena,decoded.value.pixels,3,1,1)
 check(encoded.ok && bytes.equal(encoded.value,"P5\n3 1\n255\n\n# "))
 decoded = pnm.decode(&arena,"P2\n3 1\n10\n0 5 10\n")
 check(decoded.ok && bytes.equal(decoded.value.pixels,"\x00\x80\xff"))
 decoded = pnm.decode(&arena,"P5\n1 1\n255#comment\n\x7f")
 check(decoded.ok && bytes.equal(decoded.value.pixels,"\x7f"))
 mark := mem.arena_mark(&arena)
 check(!pnm.decode(&arena,"P2\n1 1\n2\n3").ok && mem.arena_mark(&arena) == mark)
 check(!pnm.decode(&arena,"P6\n4294967295 4294967295\n255\n").ok && mem.arena_mark(&arena) == mark)
 check(!pnm.decode(&arena,"P5\n1 1\n65536\n\x00").ok && mem.arena_mark(&arena) == mark)
 check(!pnm.decode(&arena,"P5\n0 1\n255\n").ok && mem.arena_mark(&arena) == mark)
 check(!pnm.decode(&arena,"P5\n1 1\n255\n").ok && mem.arena_mark(&arena) == mark)
 check(!pnm.decode(&arena,"P2\n2 1\n255\n1").ok && mem.arena_mark(&arena) == mark)
 golden := "P6\n2 1\n255\n\xff\x00\x77\x00\xff\xff"
 for cut in 0..#len(golden) { check(!pnm.decode(&arena,golden[..cut]).ok && mem.arena_mark(&arena) == mark) }
 for i in 0..#len(golden) {
  for bit in 0..8 {
   data := mem.push_array(u8,&arena,#len(golden))
   for j in 0..#len(data) { data[j] = golden[j] }
   data[i] ^= #cast(u8,1) << #cast(u8,bit)
   _ = pnm.decode(&arena,data)
   mem.arena_rewind(&arena,mark)
  }
 }
 check(pnm.encode(&arena,"",1,1,4).kind == errors.Kind.InvalidInput && mem.arena_mark(&arena) == mark)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-pnm-') as directory:
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
print('PASS PNM: binary/plain, sample scaling, delimiters, malformed input and cross-targets')
