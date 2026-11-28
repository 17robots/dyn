#!/usr/bin/env python3
"""Production GLX swap-control dispatch and native drawable qualification."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import private_display  # hides the desktop display; see tests/private_display.py
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
MOCK=r'''use errors "std/io"
use io "std/io"
use c "std/c"
use bytes "std/bytes"
pub struct Window {display:rawptr,context:rawptr,handle:usize}
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
fn make_current(window:*Window) !io.IoErr {_=window
 make_calls+=1
 if !make_ok {fail io.IoErr.System(0)}}
// The kinds of failure these fixtures meet; Ok when a call worked.
enum Kind { Ok, NotFound, PermissionDenied, AlreadyExists, InvalidInput, WouldBlock, Interrupted, Unsupported, Capacity, System }
fn kind_of(err: io.IoErr) Kind {
 case err {
  .NotFound => { return Kind.NotFound }
  .PermissionDenied => { return Kind.PermissionDenied }
  .AlreadyExists => { return Kind.AlreadyExists }
  .InvalidInput => { return Kind.InvalidInput }
  .WouldBlock => { return Kind.WouldBlock }
  .Interrupted => { return Kind.Interrupted }
  .Unsupported => { return Kind.Unsupported }
  .Capacity => { return Kind.Capacity }
  .System => { return Kind.System }
 }
}
struct Failure { kind: Kind, native: isize }
fn failure_of(err: io.IoErr) Failure {
  case err {
    .System(code) => { return Failure{ kind: Kind.System, native: code } }
    _ => { return Failure{ kind: kind_of(err) } }
  }
}
fn interval(window:*Window,value:i32) Failure {
 set_swap_interval(window,value) catch err { return failure_of(err) }
 return Failure{}
}
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
 value:=#slice(name, c.string_length(name,256))
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
 check(interval(&closed,0).kind==Kind.InvalidInput)
 check(interval(nil,0).kind==Kind.InvalidInput && make_calls==0 && lookups==0)
 host:=Window{display:#cast(rawptr,1),context:#cast(rawptr,2),handle:42}
 check(interval(&host,-1).kind==Kind.InvalidInput && interval(&host,2).kind==Kind.InvalidInput && make_calls==0)
 mock_extensions="GLX_EXT_swap_control_tear GLX_MESA_swap_control_suffix XGLX_SGI_swap_control\x00"
 check(interval(&host,0).kind==Kind.Unsupported && lookups==0 && calls==0)
 restored()
 reset()
 mock_extensions="GLX_SGI_swap_control GLX_MESA_swap_control GLX_EXT_swap_control\x00"
 check(interval(&host,0).kind==Kind.Ok && calls==1 && lookups==1 && last==0 && make_calls==1)
 restored()
 check(interval(&host,1).kind==Kind.Ok && last==1)
 reset()
 ext_present=false
 check(interval(&host,0).kind==Kind.Ok && lookups==2 && calls==1 && last==0)
 restored()
 reset()
 mock_extensions="  GLX_MESA_swap_control  \x00"
 check(interval(&host,1).kind==Kind.Ok && calls==1 && lookups==1 && last==1)
 mock_status=5
 check(interval(&host,0).kind==Kind.System)
 restored()
 reset()
 mock_extensions="GLX_SGI_swap_control\x00"
 check(interval(&host,0).kind==Kind.Unsupported && lookups==0 && calls==0)
 check(interval(&host,1).kind==Kind.Ok && calls==1 && last==1)
 mock_status=2
 check(interval(&host,1).kind==Kind.System)
 restored()
 reset()
 mock_extensions="GLX_EXT_swap_control\x00"
 error_event=true
 check(interval(&host,0).kind==Kind.System && calls==1)
 restored()
 reset()
 ext_present=false
 check(interval(&host,0).kind==Kind.Unsupported && lookups==1 && calls==0)
 restored()
 reset()
 make_ok=false
 check(interval(&host,0).kind==Kind.System && calls==0 && lookups==0)
 restored()
 reset()
 nil_mock_extensions=true
 check(interval(&host,0).kind==Kind.Unsupported && calls==0)
 restored()
 reset()
 query_error=true
 nil_mock_extensions=true
 check(interval(&host,0).kind==Kind.System && calls==0)
 restored()
 reset()
 query_error=true
 mock_extensions="GLX_not_swap_control\x00"
 check(interval(&host,0).kind==Kind.System && calls==0)
 restored()
}
'''
NATIVE=r'''use window "vendor/window/x11"
use errors "std/io"
use io "std/io"
// The kinds of failure these fixtures meet; Ok when a call worked.
enum Kind { Ok, NotFound, PermissionDenied, AlreadyExists, InvalidInput, WouldBlock, Interrupted, Unsupported, Capacity, System }
fn kind_of(err: io.IoErr) Kind {
 case err {
  .NotFound => { return Kind.NotFound }
  .PermissionDenied => { return Kind.PermissionDenied }
  .AlreadyExists => { return Kind.AlreadyExists }
  .InvalidInput => { return Kind.InvalidInput }
  .WouldBlock => { return Kind.WouldBlock }
  .Interrupted => { return Kind.Interrupted }
  .Unsupported => { return Kind.Unsupported }
  .Capacity => { return Kind.Capacity }
  .System => { return Kind.System }
 }
}
struct Failure { kind: Kind, native: isize }
fn failure_of(err: io.IoErr) Failure {
  case err {
    .System(code) => { return Failure{ kind: Kind.System, native: code } }
    _ => { return Failure{ kind: kind_of(err) } }
  }
}
fn window_set_swap_interval(p0:*window.Window, p1:i32) Failure {
  window.set_swap_interval(p0, p1) catch err { return failure_of(err) }
  return Failure{}
}

fn window_open(p0: *window.Window, p1: []const u8, p2, p3: i32) Failure {
  window.open(p0, p1, p2, p3) catch err { return failure_of(err) }
  return Failure{}
}

fn window_swap(p0: *window.Window) Failure {
  window.swap(p0) catch err { return failure_of(err) }
  return Failure{}
}

fn check(ok:bool){if !ok {#panic("native swap interval")}}
fn main(){
 host:=window.Window{}
 check(window_open(&host,"swap interval oracle",96,72).kind == Kind.Ok)
 defer window.close(&host)
 other:=window.Window{}
 check(window_open(&other,"swap interval other context",64,64).kind == Kind.Ok)
 defer window.close(&other)
 context_name:="glXGetCurrentContext\x00"
 native_context:=#cast(fn()rawptr,window.gl_proc(&context_name[0]))
 check(native_context!=nil)
 check(native_context()==other.context)
 immediate:=window_set_swap_interval(&host,0)
 check(immediate.kind==Kind.Ok || immediate.kind==Kind.Unsupported)
 check(native_context()==host.context)
 synced:=window_set_swap_interval(&host,1)
 check(synced.kind==Kind.Ok || synced.kind==Kind.Unsupported)
 restored:=window_set_swap_interval(&host,0)
 check(restored.kind==Kind.Ok || restored.kind==Kind.Unsupported)
 for frame in 0..8 {check(window_swap(&host).kind == Kind.Ok)}
 if immediate.kind==Kind.Ok {io.print("PASS native GLX immediate interval available\n")}
 else {io.print("PASS native GLX reports immediate interval unsupported\n")}
 if synced.kind==Kind.Ok {io.print("PASS native GLX one-refresh interval available\n")}
 else {io.print("PASS native GLX reports one-refresh interval unsupported\n")}
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
