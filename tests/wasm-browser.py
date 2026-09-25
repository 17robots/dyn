#!/usr/bin/env python3
"""Execute browser-target modules through the JavaScript WebAssembly interface."""
import os, shlex, subprocess, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DYN = os.environ.get('DYN', str(ROOT / 'build/dyn'))
def run(args, **kw):
    result = subprocess.run(list(map(str, args)), cwd=ROOT, text=True, capture_output=True, **kw)
    if result.returncode: raise RuntimeError(shlex.join(map(str,args))+"\n"+result.stdout+result.stderr)
    return result
source = r'''
use "std/mem" mem
extern fn host_add "host_add"(a: i32, b: i32) i32
struct Pair { x: i32, y: usize }
struct Single { x: f32 }
extern fn pair "c_pair"(p: Pair) Pair
extern fn single "c_single"(p: Single) Single
counter: i32 = host_add(20, 22)
backing: [128]u8
arena: mem.Arena = mem.arena_from_buffer(backing[..])
pub fn value() i32 { return counter }
pub fn increment() { counter += 1 }
pub fn layout() usize { return #sizeof(usize)*100 + #sizeof(rawptr)*10 + #sizeof([]u8) }
pub fn arithmetic(a: isize, b: isize) isize { return a / b }
pub fn big(a: i64) i64 { return a + 1 }
pub fn alloc(n: usize) rawptr { return #cast(rawptr) mem.arena_try_push(&arena, n, 4).memory }
pub fn reset() { mem.arena_reset(&arena) }
pub fn total(data: *u32, n: usize) u32 {
  values := data[..n]
  result: u32 = 0
  for value in values { result += value }
  return result
}
pub fn abi() bool {
  p := pair(Pair{ x: 7, y: 9 })
  s := single(Single{ x: 2.5 })
  return p.x == 8 && p.y == 11 && s.x == 3.5
}
pub fn pool_test() bool {
  mem.arena_reset(&arena)
  pool := mem.pool_init(&arena, 2, 4, 4)
  first := mem.pool_acquire(&pool)
  second := mem.pool_acquire(&pool)
  if mem.pool_try_acquire(&pool) != nil { return false }
  mem.pool_release(&pool, first)
  same := mem.pool_acquire(&pool)
  mem.pool_release(&pool, same) mem.pool_release(&pool, second)
  return same == first && mem.pool_available(&pool) == 2
}
pub fn heap_available() bool { created := mem.arena_create(32) if !created.ok { return false } return mem.arena_release(&created.arena).ok }
pub fn wide_index(index: u64) u8 { return backing[index] }
pub fn fail() { #panic("test trap") }
'''
with tempfile.TemporaryDirectory(prefix='dyn-wasm-') as directory:
    work = Path(directory); module = work/'module'; module.mkdir()
    (module/'main.dyn').write_text(source)
    (work/'oracle.c').write_text('struct Pair { int x; unsigned y; }; struct Single { float x; };\nstruct Pair c_pair(struct Pair p) { p.x++; p.y+=2; return p; }\nstruct Single c_single(struct Single p) { p.x+=1; return p; }\n')
    run([*shlex.split(os.environ.get('CLANG', 'clang')), '--target=wasm32-unknown-unknown', '-ffreestanding', '-c', work/'oracle.c', '-o', work/'oracle.o'])
    for flags in ([], ['--release']):
        output = work/'test.wasm'
        run([DYN, 'build', module, '--target', 'wasm32-browser', '--shared', '--link', work/'oracle.o', '--output', output, *flags])
        js = r'''
const assert = require('node:assert/strict');
const bytes = require('node:fs').readFileSync(process.argv[1]);
(async () => {
  const {instance,module} = await WebAssembly.instantiate(bytes,{env:{host_add:(a,b)=>a+b}});
  assert.deepEqual(WebAssembly.Module.imports(module),[{module:'env',name:'host_add',kind:'function'}]);
  assert.ok(WebAssembly.Module.exports(module).every(x=>!x.name.startsWith('dyn_m')));
  const e=instance.exports;
  e.dyn_initialize(); assert.equal(e.value(),42); e.increment(); e.dyn_initialize(); assert.equal(e.value(),43);
  assert.equal(e.layout(),448); assert.equal(e.arithmetic(-9,2),-4); assert.equal(e.big(99n),100n);
  assert.equal(e.abi(),1); assert.equal(e.heap_available(),1);
  const p=e.alloc(16)>>>0; assert.ok(p); new Uint32Array(e.memory.buffer,p,4).set([7,8,9,10]);
  assert.equal(e.total(p,4),34); assert.equal(e.alloc(256),0); e.reset(); assert.equal(e.alloc(16)>>>0,p);
  assert.equal(e.pool_test(),1);
  const another = await WebAssembly.instantiate(bytes,{env:{host_add:(a,b)=>a+b}});
  another.instance.exports.dyn_initialize();
  assert.throws(()=>another.instance.exports.wide_index(4294967296n),WebAssembly.RuntimeError);
  assert.throws(()=>e.fail(),WebAssembly.RuntimeError);
})().catch(e=>{console.error(e);process.exit(1)});
'''
        run(['node', '-e', js, output])
        run([DYN, 'build', ROOT/'projects/browser-canvas', '--target', 'wasm32-browser', '--shared', '--output', output, *flags])
        run(['node', '-e', r'''
const assert=require('node:assert/strict');
(async()=>{let seen=0; const {instance}=await WebAssembly.instantiate(require('node:fs').readFileSync(process.argv[1]),{env:{pixels_changed:n=>seen=n}});const e=instance.exports;e.dyn_initialize();const p=e.allocate(4);new Uint8Array(e.memory.buffer,p,4).set([255,0,0,255]);e.grayscale(p,1);assert.deepEqual([...new Uint8Array(e.memory.buffer,p,4)],[76,76,76,255]);assert.equal(seen,1)})().catch(e=>{console.error(e);process.exit(1)});
''', output])
    for bad in ['pub fn size() usize { return #sizeof([4294967296]u8) }', 'struct Huge { a: [2147483648]u8, b: [2147483648]u8 } pub fn size() usize { return #sizeof(Huge) }', 'pub fn bad() usize { return 4294967296 }', 'pub fn bad() isize { return #syscall(1) }', 'pub fn dyn_initialize() {}']:
        (module/'main.dyn').write_text(bad)
        result=subprocess.run([DYN,'build',str(module),'--target','wasm32-browser','--shared','--output',str(work/'bad.wasm')],cwd=ROOT,capture_output=True,text=True)
        assert result.returncode and 'error:' in result.stderr, result.stderr
print('PASS browser Wasm: JS imports/exports, 32-bit layout, C ABI, initialization, arenas, traps, canvas (debug/release)')
