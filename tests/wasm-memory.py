#!/usr/bin/env python3
"""Growth, reuse/coalescing, fixed buffers and out-of-memory traps in real Wasm."""
import os, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=os.environ.get('DYN',str(ROOT/'build/dyn'))
source=r'''
use mem "std/mem"
arenas: [8]*mem.Arena
pub fn allocate(slot: usize, size: usize) usize {
  made := mem.arena_alloc(size + mem.ArenaHeader)
  arenas[slot] = made
  return #cast(usize, &mem.push_bytes(arenas[slot], size)[0])
}
pub fn release(slot: usize) bool {
  mem.arena_release(arenas[slot])
  arenas[slot] = nil
  return true
}
pub fn fixed() bool {
  bytes: [8 + mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(bytes[..])
  arena = mem.arena_from_buffer(arena.data[..mem.ArenaHeader + 8])
  _ = mem.push_bytes(arena, 8)
  return mem.arena_used(arena) == 8
}
pub fn growing() bool {
  arena := mem.arena_alloc(65536 + mem.ArenaHeader)
  first := mem.push_array<u64>(arena, 8192)
  first[0] = 42
  second := mem.push_array<u64>(arena, 8192)
  second[0] = 17
  if first[0] != 42 || arena.current == arena || arena.current.previous != arena { return false }
  mem.arena_reset(arena)
  reused := mem.push_array<u64>(arena, 8192)
  ok := arena.current == arena && reused[0] == 0
  mem.arena_release(arena)
  return ok
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
 const before=e.memory.buffer.byteLength;assert.throws(()=>e.allocate(6,4*1024*1024),WebAssembly.RuntimeError);assert.equal(e.memory.buffer.byteLength,before);assert.equal(new Uint8Array(e.memory.buffer)[held],79);
 assert.throws(()=>e.allocate(6,0xffffffff),WebAssembly.RuntimeError);
 for(const [a,b] of [[0n,0xffffffffffffffffn],[0xffffffffn,0xffffffffn],[0x100000000n,0xffffffffn],[9223372036854775807n,2n]]) assert.equal(BigInt.asUintN(64,e.multiply(a,b)),a*b);
 
})().catch(e=>{console.error(e);process.exit(1)});
'''
with tempfile.TemporaryDirectory(prefix='dyn-wasm-memory-') as directory:
 work=Path(directory);(work/'main.dyn').write_text(source)
 for flags in ([],['--release']):
  subprocess.run([DYN,'build',str(work),'--target','wasm32-browser','--shared','--link','--max-memory=3145728','--output',str(work/'test.wasm'),*flags],cwd=ROOT,check=True,capture_output=True,text=True,timeout=120)
  result=subprocess.run(['node','-e',js,str(work/'test.wasm')],capture_output=True,text=True,timeout=30)
  assert result.returncode==0,result.stdout+result.stderr
print('PASS Wasm arena growth, stable pointers, reuse, split/coalesce, chained arenas, OOM, checked u64 multiplication (debug/release)')
