#!/usr/bin/env python3
"""Validate the compiler-free runtime against wasm-ld and JavaScript Wasm."""
import os
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='dyn-wasm-runtime-') as directory:
    work = Path(directory)
    subprocess.run([sys.executable, ROOT / 'tools/wasm-runtime.py', '--output-dir', work], check=True)
    subprocess.run([os.environ.get('WASM_LD', 'wasm-ld'), '--no-entry', '--export-all', '--allow-undefined', work / 'dynrt_wasm.o', work / 'dynrt_wasi_support.o', '-o', work / 'runtime.wasm'], check=True)
    spec = importlib.util.spec_from_file_location('wasm_runtime', ROOT / 'tools/wasm-runtime.py')
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    main = runtime.Object()
    main.function('__original_main', [], [runtime.I32], [runtime.const(42)])
    main.write(work / 'main.o')
    subprocess.run([os.environ.get('WASM_LD', 'wasm-ld'), '--no-entry', '--allow-undefined', work / 'main.o', work / 'dynrt_wasi_start.o', '-o', work / 'start.wasm'], check=True)
    subprocess.run([os.environ.get('NODE', 'node'), '-e', "const fs=require('node:fs'),assert=require('node:assert/strict'); (async()=>{let exit; const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:{proc_exit(n){exit=n;throw 'exit';}}}); assert.throws(()=>instance.exports._start(),x=>x==='exit'); assert.equal(exit,42);})().catch(e=>{console.error(e);process.exit(1)});", work / 'start.wasm'], check=True)
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
  let e;
  const seen = [];
  const wasi = {
    fd_write(fd, iov, count, result) {
      const v = new DataView(e.memory.buffer);
      assert.equal(fd, 9); assert.equal(count, 1);
      assert.equal(v.getUint32(iov, true), 100); assert.equal(v.getUint32(iov + 4, true), 3);
      v.setUint32(result, 3, true); seen.push('write'); return 0;
    },
    fd_read(fd, iov, count, result) {
      const v = new DataView(e.memory.buffer);
      assert.equal(fd, 8); assert.equal(count, 1);
      assert.equal(v.getUint32(iov, true), 200); assert.equal(v.getUint32(iov + 4, true), 4);
      v.setUint32(result, 4, true); seen.push('read'); return 0;
    },
    fd_close(fd) { assert.equal(fd, 7); return 6; },
    args_sizes_get(a, b) { assert.equal(a, 10); assert.equal(b, 20); return 5; },
    args_get(a, b) { assert.equal(a, 30); assert.equal(b, 40); return 4; },
    path_open(...args) { assert.deepEqual(args, [3, 0, 100, 5, 0, 2n, 0n, 0, 200]); return 3; },
    random_get(a, b) { assert.equal(a, 100); assert.equal(b, 8); return 2; },
    clock_time_get(a, b, c) { assert.equal(a, 1); assert.equal(b, 123n); assert.equal(c, 100); return 1; },
  };
  ({instance: {exports: e}} = await WebAssembly.instantiate(fs.readFileSync(process.argv[1]), {wasi_snapshot_preview1:wasi}));
  for (const a of [0,-0,1,-1,2,100,Infinity,-Infinity,NaN,1e308,5e-324,-1e-308]) {
    for (const b of [0,-0,1,-1,2,3,Infinity,NaN,1e-300,5e-324]) {
      assert.ok(Object.is(e.fmod(a,b),a%b), `f64 ${a} % ${b}`);
      const x=Math.fround(a), y=Math.fround(b);
      assert.ok(Object.is(e.fmodf(x,y),Math.fround(x%y)), `f32 ${x} % ${y}`);
    }
  }
  const randomBits = new DataView(new ArrayBuffer(8));
  let randomState = 17n;
  const randomFloat = () => {
    randomState = (randomState * 6364136223846793005n + 1442695040888963407n) & ((1n<<64n)-1n);
    randomBits.setBigUint64(0,randomState,true);
    return randomBits.getFloat64(0,true);
  };
  for (let i=0;i<10000;i++) {
    const a=randomFloat(), b=randomFloat();
    assert.ok(Object.is(e.fmod(a,b),a%b), `random f64 ${a} % ${b}`);
    const x=Math.fround(a), y=Math.fround(b);
    assert.ok(Object.is(e.fmodf(x,y),Math.fround(x%y)), `random f32 ${x} % ${y}`);
  }
  let bytes = new Uint8Array(e.memory.buffer);
  assert.equal(e.memset(100, 0x123, 8), 100); assert.deepEqual([...bytes.slice(100,108)], Array(8).fill(0x23));
  bytes.set([1,2,3,4,5,6,7,8],100);
  assert.equal(e.memcpy(200,100,8),200); assert.deepEqual([...bytes.slice(200,208)], [1,2,3,4,5,6,7,8]);
  e.memmove(102,100,6); assert.deepEqual([...bytes.slice(100,108)], [1,2,1,2,3,4,5,6]);
  e.memmove(100,102,6); assert.deepEqual([...bytes.slice(100,106)], [1,2,3,4,5,6]);
  e.memmove(0,0,0); e.memcpy(0,0,0); e.memset(0,0,0);
  const mask = (1n << 64n)-1n, mask128 = (1n << 128n)-1n;
  let seed = 17n;
  const next = () => (seed = (seed*6364136223846793005n+1442695040888963407n)&mask);
  const vectors = [[0n,0n], [mask128,mask128], [1n<<127n, 2n], [mask,mask]];
  for (let i=0;i<1000;i++) vectors.push([(next()<<64n)|next(),(next()<<64n)|next()]);
  for (const [a,b] of vectors) {
    e.__multi3(256,a&mask,a>>64n,b&mask,b>>64n);
    const v = new DataView(e.memory.buffer);
    assert.equal(v.getBigUint64(256,true)|(v.getBigUint64(264,true)<<64n), (a*b)&mask128);
  }
  assert.equal(e.dyn_wasi_write(9,100,3,300),0); assert.equal(e.dyn_wasi_read(8,200,4,304),0);
  assert.deepEqual(seen,['write','read']);
  assert.equal(e.dyn_wasi_close(7),6); assert.equal(e.dyn_wasi_args_sizes(10,20),5);
  assert.equal(e.dyn_wasi_args(30,40),4); assert.equal(e.dyn_wasi_open_read(3,100,5,200),3);
  assert.equal(e.dyn_wasi_random(100,8),2); assert.equal(e.dyn_wasi_clock(1,123n,100),1);
  assert.equal(e.dyn_time_wasi_clock(1,123n,100),1);
  assert.throws(()=>e.dyn_panic(0,0),WebAssembly.RuntimeError);
  const pages = e.memory.buffer.byteLength/65536;
  assert.equal(e.dyn_wasm_grow_pages(1),pages); assert.equal(e.memory.buffer.byteLength,(pages+1)*65536);
})().catch(e => { console.error(e); process.exit(1); });
'''
    subprocess.run([os.environ.get('NODE', 'node'), '-e', script, work / 'runtime.wasm'], check=True)
print('Wasm runtime: memory operations, 128-bit multiplication, WASI adapter ABI, growth and traps passed')
