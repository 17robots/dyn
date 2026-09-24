#!/usr/bin/env python3
"""Growth, reuse/coalescing, fixed buffers and allocation failure in real Wasm."""
import os, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=os.environ.get('DYN',str(ROOT/'build/dyn'))
source=r'''
use "std/mem" mem
arenas: [8]mem.Arena
pub fn allocate(slot: usize, size: usize) usize {
  made := mem.arena_create(size)
  if !made.ok { return 0 }
  arenas[slot] = made.arena
  return #cast(usize) mem.arena_push(&arenas[slot], size, 1)
}
pub fn release(slot: usize) bool { return mem.arena_release(&arenas[slot]).ok }
pub fn fixed() bool {
  bytes: [8]u8 arena := mem.arena_from_buffer(bytes[..])
  _ = mem.arena_push(&arena, 8, 1)
  return !mem.arena_try_push(&arena, 1, 1).ok
}
pub fn growing() bool {
  arena := mem.growing_create(65536)
  first := mem.growing_push(&arena, 65536, 8) first.* = 42
  second := mem.growing_push(&arena, 65536, 8) second.* = 17
  if first.* != 42 { return false }
  mem.growing_reset(&arena)
  reused := mem.growing_push(&arena, 65536, 8)
  ok := first == reused
  return mem.growing_release(&arena).ok && ok
}
pub fn multiply(a: u64, b: u64) u64 { return a * b }
'''
js=r'''
const assert=require('node:assert/strict'),fs=require('fs');
(async()=>{
 const bytes=fs.readFileSync(process.argv[1]);const {instance}=await WebAssembly.instantiate(bytes);const e=instance.exports;e.dyn_initialize();
 const original=e.memory.buffer;const p=e.allocate(0,90000)>>>0;assert.ok(p);assert.equal(original.byteLength,0);
 new Uint8Array(e.memory.buffer)[p]=42;
 const q=e.allocate(1,90000)>>>0;assert.ok(q);assert.equal(new Uint8Array(e.memory.buffer)[p],42);
 const peak=e.memory.buffer.byteLength;
 assert.equal(e.release(0),1);assert.equal(e.release(1),1);
 const joined=e.allocate(2,200000)>>>0;assert.equal(joined,p);assert.equal(e.memory.buffer.byteLength,peak);assert.equal(e.release(2),1);
 const split=e.allocate(3,1000)>>>0;assert.equal(split,p);const tail=e.allocate(4,90000)>>>0;assert.equal(tail,p+65536);
 assert.equal(e.release(4),1);assert.equal(e.release(3),1);assert.equal(e.growing(),1);assert.equal(e.fixed(),1);
 const held=e.allocate(5,16)>>>0;new Uint8Array(e.memory.buffer)[held]=79;
 const before=e.memory.buffer.byteLength;assert.equal(e.allocate(6,4*1024*1024),0);assert.equal(e.memory.buffer.byteLength,before);assert.equal(new Uint8Array(e.memory.buffer)[held],79);
 assert.equal(e.allocate(6,0xffffffff),0);
 for(const [a,b] of [[0n,0xffffffffffffffffn],[0xffffffffn,0xffffffffn],[0x100000000n,0xffffffffn],[9223372036854775807n,2n]]) assert.equal(BigInt.asUintN(64,e.multiply(a,b)),a*b);
 const overflow=await WebAssembly.instantiate(bytes);overflow.instance.exports.dyn_initialize();assert.throws(()=>overflow.instance.exports.multiply(0xffffffffffffffffn,2n),WebAssembly.RuntimeError);
})().catch(e=>{console.error(e);process.exit(1)});
'''
with tempfile.TemporaryDirectory(prefix='dyn-wasm-memory-') as directory:
 work=Path(directory);(work/'main.dyn').write_text(source)
 for flags in ([],['--release']):
  subprocess.run([DYN,'build',str(work),'--target','wasm32-browser','--shared','--link','--max-memory=3145728','--output',str(work/'test.wasm'),*flags],cwd=ROOT,check=True,capture_output=True,text=True)
  result=subprocess.run(['node','-e',js,str(work/'test.wasm')],capture_output=True,text=True,timeout=30)
  assert result.returncode==0,result.stdout+result.stderr
print('PASS Wasm arena growth, stable pointers, reuse, split/coalesce, growing arenas, OOM, checked u64 multiplication (debug/release)')
