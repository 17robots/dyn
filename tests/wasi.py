#!/usr/bin/env python3
"""Execute WASI Preview 1 commands with explicit host-provided descriptors."""
import os, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=os.environ.get('DYN',str(ROOT/'build/dyn'))
source=r'''
use "std/mem" mem
use "std/os/wasi" wasi
use "std/io" io
use "std/terminal" terminal
fn main() {
  arena := mem.arena_create(65536) if !arena.ok { #panic("arena") }
  defer { _ = mem.arena_release(&arena.arena) }
  arguments := wasi.arguments(&arena.arena)
  if !arguments.ok || #len(arguments.values) != 3 || #len(arguments.values[2]) != 5 { #panic("args") }
  tiny: [1]u8 buffer := mem.arena_from_buffer(tiny[..])
  failed := wasi.arguments(&buffer)
  if failed.ok || mem.arena_used(&buffer) != 0 { #panic("args rollback") }
  file := wasi.open_read(3, "input.txt")
  if #len(arguments.values[1]) == 4 {
    if file.ok { #panic("unexpected preopen") }
    _ = io.println(terminal.stdout(), "denied") return
  }
  if !file.ok { #panic("open") }
  defer { _ = wasi.close(file.fd) }
  data: [16]u8
  result := wasi.read(file.fd, data[..])
  if result.status != io.Status.Complete || result.transferred != 5 { #panic("read") }
  _ = io.write_all(terminal.stdout(), data[..result.transferred])
  if wasi.read(file.fd, data[..]).status != io.Status.End { #panic("EOF") }
  if wasi.read(999999, data[..]).status != io.Status.Error { #panic("bad fd") }
  result = io.read_exact(terminal.stdin(), data[..3])
  if result.transferred != 3 { #panic("stdin") }
  _ = io.write_all(terminal.stdout(), data[..3])
  if wasi.random(data[..]) != 0 { #panic("random") }
  now: u64 = 0 if wasi.clock_time(1, 0, &now) != 0 || now == 0 { #panic("clock") }
}
'''
js=r'''
const {WASI}=require('node:wasi'),fs=require('fs');
(async()=>{const wasi=new WASI({version:'preview1',args:['test',process.argv[3],'hello'],preopens:process.argv[3]==='deny'?{}:{'/data':process.argv[2]},returnOnExit:true});const {module,instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});if(WebAssembly.Module.imports(module).some(x=>x.module!=='wasi_snapshot_preview1'))throw Error('unexpected host imports');process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});
'''
with tempfile.TemporaryDirectory(prefix='dyn-wasi-') as directory:
 work=Path(directory);(work/'main.dyn').write_text(source);(work/'input.txt').write_text('hello')
 for flags in ([],['--release']):
  result=subprocess.run([DYN,'build',str(work),'--target','wasm32-wasi','--output',str(work/'test.wasm'),*flags],cwd=ROOT,capture_output=True,text=True)
  assert result.returncode==0,result.stdout+result.stderr
  for mode,expected in [('allow','helloabc'),('deny','denied\n')]:
   result=subprocess.run(['node','--no-warnings','-e',js,str(work/'test.wasm'),str(work),mode],input='abc',capture_output=True,text=True,timeout=30)
   assert result.returncode==0 and result.stdout==expected,result.stdout+result.stderr
print('PASS WASI Preview 1 arguments, arena rollback, preopened files, denied access, stdin/stdout, EOF, errors, random and clock (debug/release)')
