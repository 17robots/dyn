#!/usr/bin/env python3
"""Execute Wasm arithmetic, aliasing, evaluation-order and cleanup regressions."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = os.environ.get('DYN', str(ROOT/'build/dyn'))
SOURCE = r'''
enum(u64) Big { Zero = 0, Top = 0xFFFFFFFFFFFFFFFF }
enum(i8) Sign { Minus = -1, Zero = 0, Plus = 1 }
extern fn note "note"(value: i32)
struct Pair { x: i32, y: i32 }
pub fn rem64(a: f64,b: f64) f64 { return a % b }
pub fn rem32(a: f32,b: f32) f32 { return a % b }
pub fn high() u32 { return 4294967295 }
pub fn badenum(x: i64) u64 { return #cast(u64, #cast(Big, x)) }
pub fn goodenum(x: i64) i8 { return #cast(i8, #cast(Sign, x)) }
pub fn divsmall(x: i8, y: i8) i8 { return x / y }
pub fn remsmall(x: i8, y: i8) i8 { return x % y }
pub fn deref(p: *i32) i32 { return p.* }
pub fn cleanup(x: i32) i32 { defer { note(7) } return 10 / x }
fn mutate(p: *Pair) i32 { p.x = 99 return 0 }
fn take(p: Pair, ignored: i32) i32 { return p.x }
pub fn snapshot() i32 { p := Pair{x: 7, y: 9} return take(p, mutate(&p)) }
fn first(x: i32) i32 { return 11 }
fn second(x: i32) i32 { return 22 }
callback: fn(i32) i32 = &first
fn change() i32 { callback = &second return 0 }
pub fn order() i32 { callback = &first return callback(change()) }
'''
JS = r'''
const assert = require('node:assert/strict');
const bytes = require('node:fs').readFileSync(process.argv[1]);
(async () => {
  const notes = [];
  const fresh = async () => (await WebAssembly.instantiate(bytes, {env:{note:x=>notes.push(x)}})).instance.exports;
  const e = await fresh();
  e.dyn_initialize();
  for (const a of [0,-0,1,-1,2,100,Infinity,-Infinity,NaN,1e308,5e-324,-1e-308]) {
    for (const b of [0,-0,1,-1,2,3,Infinity,NaN,1e-300,5e-324]) {
      assert.ok(Object.is(e.rem64(a,b),a%b), `f64 ${a} % ${b}`);
      const x=Math.fround(a),y=Math.fround(b);
      assert.ok(Object.is(e.rem32(x,y),Math.fround(x%y)), `f32 ${x} % ${y}`);
    }
  }
  assert.equal(e.high(), -1);
  assert.equal(e.goodenum(-1n), -1);
  assert.equal(e.snapshot(), 7);
  assert.equal(e.order(), 11);
  for (const [name,args] of [['badenum',[-1n]],['divsmall',[-128,-1]],['remsmall',[-128,-1]],['divsmall',[1,0]],['deref',[1025]]]) {
    const instance = await fresh();
    assert.throws(()=>instance[name](...args), WebAssembly.RuntimeError, name);
  }
  const cleanup = await fresh();
  assert.throws(()=>cleanup.cleanup(0), WebAssembly.RuntimeError);
  assert.deepEqual(notes,[7]);
})().catch(e=>{console.error(e);process.exit(1)});
'''
with tempfile.TemporaryDirectory(prefix='dyn-wasm-semantics-') as directory:
    work = Path(directory)
    module = work/'module'
    module.mkdir()
    (module/'main.dyn').write_text(SOURCE)
    for flags in ([], ['--release']):
        output = work/'test.wasm'
        subprocess.run([DYN, 'build', str(module), '--target', 'wasm32-browser',
                        '--shared', '--output', str(output), *flags], cwd=ROOT, check=True)
        subprocess.run(['node', '-e', JS, str(output)], check=True)
print('PASS Wasm arithmetic, aliasing, evaluation order and cleanup')
