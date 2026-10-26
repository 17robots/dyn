#!/usr/bin/env python3
"""O3 must not emit dead bodies whose tables were replaced by inlining."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
NODE = os.environ.get('NODE', 'node')
if not shutil.which(NODE):
    print('SKIP Wasm dead inline: Node unavailable')
    raise SystemExit(0)
SOURCE = '''use "std/mem" mem
fn main() {
  arena := mem.Arena{}
  value := mem.push(i32, &arena)
  value.* = 42
  if value.* != 42 { #panic("live allocation") }
  mem.arena_release(&arena)
}
'''
WASI = "const {WASI}=require('node:wasi'),fs=require('node:fs');(async()=>{const wasi=new WASI({version:'preview1',returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});"
LIBRARY = '''use "std/mem" mem
extern fn missing "unused_missing"() i32
fn dead() i32 { return missing() }
fn initial() i32 { return 3 }
state: i32 = initial()
fn plus(value: i32) i32 { return value + state }
callback: fn(i32) i32 = plus
pub fn api(value: i32) i32 {
  arena := mem.Arena{}
  slot := mem.push(i32, &arena)
  slot.* = callback(value)
  result := slot.*
  mem.arena_release(&arena)
  return result
}
'''
BROWSER = "const fs=require('node:fs'),assert=require('node:assert/strict');(async()=>{const {instance,module}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{env:{unused_missing:()=>{throw Error('dead function ran')}}});assert.ok(WebAssembly.Module.imports(module).every(x=>x.name==='unused_missing'));instance.exports.dyn_initialize();assert.equal(instance.exports.api(39),42);})().catch(e=>{console.error(e);process.exit(1)});"
with tempfile.TemporaryDirectory(prefix='dyn-wasm-dead-inline-') as directory:
    work = Path(directory)
    for target, source, script in (('wasm32-wasi', SOURCE, WASI), ('wasm32-browser', LIBRARY, BROWSER)):
        (work / 'main.dyn').write_text(source)
        for level in ('2', '3'):
            output = work / 'test.wasm'
            command = [DYN, 'build', str(work), '--target', target, '--release', '--opt-level', level, '--no-cache', '--quiet', '--output', str(output)]
            if target == 'wasm32-browser':
                command += ['--shared']
            subprocess.run(command, check=True, timeout=300)
            subprocess.run([NODE, '--no-warnings', '-e', script, str(output)], check=True, timeout=30)
print('PASS Wasm dead inline: O2/O3, live allocation, exports, initializer calls, indirect callbacks and unused imports')
