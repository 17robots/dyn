#!/usr/bin/env python3
"""Production GLX swap-control dispatch and native drawable qualification."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
MOCK=r'''use "std/errors" errors
use "std/c" c
use "std/bytes" bytes
pub struct Window {display:rawptr,context:rawptr,handle:usize}
pub struct Result {kind:errors.Kind,ok:bool}
context_error_display:rawptr
context_error_seen:bool
context_previous_handler:fn(rawptr,rawptr)i32
handler:fn(rawptr,rawptr)i32
mock_extensions:[]const u8="\x00"
lookups:usize
calls:usize
last:i32
make_calls:usize
make_ok:bool=true
ext_present:bool=true
mesa_present:bool=true
sgi_present:bool=true
error_event:bool
mock_status:i32
query_error:bool
nil_mock_extensions:bool
fn check(ok:bool){if !ok {#panic("swap interval dispatch")}}
fn outer(display,event:rawptr)i32 {_=display
 _=event
 return 0}
fn context_error(display,event:rawptr)i32 {_=event
 check(display==context_error_display)
 context_error_seen=true
 return 0}
fn set_error_handler(value:fn(rawptr,rawptr)i32)fn(rawptr,rawptr)i32 {
 old:=handler
 handler=value
 return old
}
fn sync(display:rawptr,discard:i32)i32 {_=display
 _=discard
 return 0}
fn screen(display:rawptr)i32 {_=display
 return 7}
fn make_current(window:*Window)Result {_=window
 make_calls+=1
 return Result{ok:make_ok}}
fn swap_extensions(display:rawptr,screen_id:i32)*const u8 {
 check(display==#cast(rawptr,1) && screen_id==7)
 if query_error {_=handler(display,nil)}
 if nil_mock_extensions {return nil}
 return &mock_extensions[0]
}
fn ext(display:rawptr,drawable:usize,interval:i32) {
 check(display==#cast(rawptr,1) && drawable==42)
 calls+=1
 last=interval
 if error_event {_=handler(display,nil)}
}
fn mesa(interval:u32)i32 {calls+=1
 last=#cast(i32,interval)
 if error_event {_=handler(#cast(rawptr,1),nil)}
 return mock_status}
fn sgi(interval:i32)i32 {calls+=1
 last=interval
 return mock_status}
fn gl_proc(name:*const u8)rawptr {
 lookups+=1
 value:=name[..c.string_length(name,256)]
 if bytes.equal(value,"glXSwapIntervalEXT") && ext_present {return #cast(rawptr,ext)}
 if bytes.equal(value,"glXSwapIntervalMESA") && mesa_present {return #cast(rawptr,mesa)}
 if bytes.equal(value,"glXSwapIntervalSGI") && sgi_present {return #cast(rawptr,sgi)}
 return nil
}
fn reset(){lookups=0
 calls=0
 make_calls=0
 mock_status=0
 error_event=false
 ext_present=true
 mesa_present=true
 sgi_present=true
 make_ok=true
 query_error=false
 nil_mock_extensions=false
 handler=outer
 context_error_display=#cast(rawptr,8)
 context_previous_handler=outer
 context_error_seen=true}
fn restored(){check(handler==outer && context_error_display==#cast(rawptr,8) && context_previous_handler==outer && context_error_seen)}
fn main(){
 reset()
 closed:=Window{}
 check(set_swap_interval(&closed,0).kind==errors.Kind.InvalidState)
 check(set_swap_interval(nil,0).kind==errors.Kind.InvalidState && make_calls==0 && lookups==0)
 host:=Window{display:#cast(rawptr,1),context:#cast(rawptr,2),handle:42}
 check(set_swap_interval(&host,-1).kind==errors.Kind.InvalidInput && set_swap_interval(&host,2).kind==errors.Kind.InvalidInput && make_calls==0)
 mock_extensions="GLX_EXT_swap_control_tear GLX_MESA_swap_control_suffix XGLX_SGI_swap_control\x00"
 check(set_swap_interval(&host,0).kind==errors.Kind.Unsupported && lookups==0 && calls==0)
 restored()
 reset()
 mock_extensions="GLX_SGI_swap_control GLX_MESA_swap_control GLX_EXT_swap_control\x00"
 check(set_swap_interval(&host,0).ok && calls==1 && lookups==1 && last==0 && make_calls==1)
 restored()
 check(set_swap_interval(&host,1).ok && last==1)
 reset()
 ext_present=false
 check(set_swap_interval(&host,0).ok && lookups==2 && calls==1 && last==0)
 restored()
 reset()
 mock_extensions="  GLX_MESA_swap_control  \x00"
 check(set_swap_interval(&host,1).ok && calls==1 && lookups==1 && last==1)
 mock_status=5
 check(set_swap_interval(&host,0).kind==errors.Kind.System)
 restored()
 reset()
 mock_extensions="GLX_SGI_swap_control\x00"
 check(set_swap_interval(&host,0).kind==errors.Kind.Unsupported && lookups==0 && calls==0)
 check(set_swap_interval(&host,1).ok && calls==1 && last==1)
 mock_status=2
 check(set_swap_interval(&host,1).kind==errors.Kind.System)
 restored()
 reset()
 mock_extensions="GLX_EXT_swap_control\x00"
 error_event=true
 check(set_swap_interval(&host,0).kind==errors.Kind.System && calls==1)
 restored()
 reset()
 ext_present=false
 check(set_swap_interval(&host,0).kind==errors.Kind.Unsupported && lookups==1 && calls==0)
 restored()
 reset()
 make_ok=false
 check(set_swap_interval(&host,0).kind==errors.Kind.System && calls==0 && lookups==0)
 restored()
 reset()
 nil_mock_extensions=true
 check(set_swap_interval(&host,0).kind==errors.Kind.Unsupported && calls==0)
 restored()
 reset()
 query_error=true
 nil_mock_extensions=true
 check(set_swap_interval(&host,0).kind==errors.Kind.System && calls==0)
 restored()
 reset()
 query_error=true
 mock_extensions="GLX_not_swap_control\x00"
 check(set_swap_interval(&host,0).kind==errors.Kind.System && calls==0)
 restored()
}
'''
NATIVE=r'''use "vendor/window/x11" window
use "std/errors" errors
use "std/io" io
fn check(ok:bool){if !ok {#panic("native swap interval")}}
fn main(){
 host:=window.Window{}
 check(window.open(&host,"swap interval oracle",96,72).ok)
 defer window.close(&host)
 other:=window.Window{}
 check(window.open(&other,"swap interval other context",64,64).ok)
 defer window.close(&other)
 context_name:="glXGetCurrentContext\x00"
 native_context:=#cast(fn()rawptr,window.gl_proc(&context_name[0]))
 check(native_context!=nil)
 check(native_context()==other.context)
 immediate:=window.set_swap_interval(&host,0)
 check(immediate.ok || immediate.kind==errors.Kind.Unsupported)
 check(native_context()==host.context)
 synced:=window.set_swap_interval(&host,1)
 check(synced.ok || synced.kind==errors.Kind.Unsupported)
 restored:=window.set_swap_interval(&host,0)
 check(restored.ok || restored.kind==errors.Kind.Unsupported)
 for frame in 0..8 {check(window.swap(&host).ok)}
 if immediate.ok {_=io.write_all(io.stdout(),"PASS native GLX immediate interval available\n")}
 else {_=io.write_all(io.stdout(),"PASS native GLX reports immediate interval unsupported\n")}
 if synced.ok {_=io.write_all(io.stdout(),"PASS native GLX one-refresh interval available\n")}
 else {_=io.write_all(io.stdout(),"PASS native GLX reports one-refresh interval unsupported\n")}
}
'''
if not __import__('sys').platform.startswith('linux'):
 print('SKIP GLX swap interval: Linux only');raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-swap-interval-') as directory:
 work=Path(directory)
 mock=work/'mock';mock.mkdir()
 source=(ROOT/'vendor/window/x11/swap_interval.dyn').read_text()
 source=source.replace('extern fn swap_extensions "glXQueryExtensionsString"(display: rawptr, screen: i32) *const u8','')
 (mock/'production.dyn').write_text(source)
 (mock/'main.dyn').write_text(MOCK)
 for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
  output=work/'mock-test'
  subprocess.run([DYN,'build',str(mock),*flags,'--quiet','--output',str(output)],check=True,timeout=120)
  subprocess.run([str(output)],check=True,timeout=30)
 native=work/'native';native.mkdir();(native/'main.dyn').write_text(NATIVE)
 for target in ('aarch64-linux','riscv64-linux'):
  subprocess.run([DYN,'build',str(native),'--release','--target',target,'--emit-object','--no-link','--quiet','--output',str(work/target)],check=True,timeout=180)
 if os.environ.get('DISPLAY'):
  for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
   output=work/'native-test'
   subprocess.run([DYN,'build',str(native),*flags,'--quiet','--output',str(output)],check=True,timeout=120)
   subprocess.run([str(output)],check=True,timeout=30)
 else: print('SKIP native GLX drawable: DISPLAY unavailable')
print('PASS GLX swap control: exact extension tokens, EXT/MESA/SGI dispatch, interval validation, current context, scoped error recovery (debug/O2/O3; ARM64/RV64 objects)')
