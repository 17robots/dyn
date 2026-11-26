#!/usr/bin/env python3
"""Execute WASI Preview 1 commands with explicit host-provided descriptors."""
import os, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=os.environ.get('DYN',str(ROOT/'build/dyn'))
source=r'''
use "std/fail"
use io "std/io"
use mem "std/mem"
use wasi "std/os/wasi"
use terminal "std/terminal"
fn main() {
  arena := mem.arena_alloc(65536)
  defer { mem.arena_release(arena) }
  status := fail.Status{ on_failure: fail.panic_on_failure }
  arguments := wasi.arguments(arena, &status)
  if arguments.len != 3 || arguments[2].len != 5 { #panic("args") }
  opening: fail.Status
  fd := wasi.open_read(&opening, 3, "input.txt")
  if arguments[1].len == 4 {
    if !opening.failed { #panic("unexpected preopen") }
    io.println("denied")
    return
  }
  if opening.failed { #panic("open") }
  defer { _ = wasi.close(fd) }
  data: [16]u8
  count := wasi.read(&status, fd, data[..])
  if count != 5 { #panic("read") }
  io.write(&status, io.stdout(), data[..count])
  if wasi.read(&status, fd, data[..]) != 0 { #panic("EOF") }
  bad: fail.Status
  _ = wasi.read(&bad, 999999, data[..])
  if !bad.failed { #panic("bad fd") }
  if io.read_exact(&status, io.stdin(), data[..3]) != 3 { #panic("stdin") }
  io.write(&status, io.stdout(), data[..3])
  if wasi.random(data[..]) != 0 { #panic("random") }
  now: u64 = 0
  if wasi.clock_time(1, 0, &now) != 0 || now == 0 { #panic("clock") }
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
