#!/usr/bin/env python3
"""Dyn/native scalar ABI and result mapping for surrounding context publication."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use "vendor/window/native" window
use "std/text/edit" edit
use "std/errors" errors
extern fn calls "probe_calls"() i32
extern fn set_status "probe_status"(status: i32)
fn check(ok: bool) { if !ok { #panic("surrounding native ABI") } }
fn main() {
  host := window.Window{handle:#cast(rawptr,1)}
  context := edit.Context{text:"hé😀",cursor:3,anchor:7,token:1234605616436508552,cause:edit.Cause.InputMethod}
  check(window.set_surrounding_text(&host,context).ok && calls()==1)
  context.cursor = 2
  check(window.set_surrounding_text(&host,context).kind==errors.Kind.InvalidInput && calls()==1)
  context.cursor = 3
  context.token = 2
  check(window.set_surrounding_text(&host,context).kind==errors.Kind.Unsupported && calls()==2)
  context.token = 3
  check(window.set_surrounding_text(&host,context).kind==errors.Kind.Capacity && calls()==3)
  context = edit.Context{text:"",token:9}
  check(window.set_surrounding_text(&host,context).ok && calls()==4)
  context = edit.Context{text:"a\0b",cursor:0,anchor:0,token:10}
  check(window.set_surrounding_text(&host,context).kind==errors.Kind.InvalidInput && calls()==4)
  check(window.set_title(&host,"hé").ok)
  check(window.set_size(&host,20,30).ok && host.width==20 && host.height==30)
  check(window.set_swap_interval(&host,1).ok)
  check(window.try_set_clipboard(&host,"hé").ok)
  check(!window.paste_pending(&host))
  window.request_paste_snapshot(&host)
  check(window.paste_status(&host).ok)
  set_status(-1)
  check(window.set_title(&host,"title").kind==errors.Kind.Unsupported)
  set_status(-2)
  check(window.try_set_clipboard(&host,"").kind==errors.Kind.Capacity)
  set_status(-3)
  check(window.try_set_clipboard(&host,"").kind==errors.Kind.InvalidInput)
  set_status(-4)
  check(window.paste_status(&host).kind==errors.Kind.InvalidState)
  set_status(0)
  check(window.set_swap_interval(&host,1).kind==errors.Kind.System)
  check(window.set_title(&host,"a\0b").kind==errors.Kind.InvalidInput)
  check(window.set_size(&host,0,1).kind==errors.Kind.InvalidInput)
  check(window.set_swap_interval(&host,-1).kind==errors.Kind.InvalidInput)
  host.handle = nil
  check(window.set_title(&host,"").kind==errors.Kind.InvalidState)
  check(window.set_size(&host,1,1).kind==errors.Kind.InvalidState)
  check(window.set_swap_interval(&host,1).kind==errors.Kind.InvalidState)
  check(window.try_set_clipboard(&host,"").kind==errors.Kind.InvalidState)
  check(window.paste_status(&host).kind==errors.Kind.InvalidState)
  check(!window.paste_pending(&host))
  window.request_paste_snapshot(&host)
  check(window.set_surrounding_text(&host,context).kind==errors.Kind.InvalidState && calls()==4)
}
'''
C=r'''#include "window.h"
#include <string.h>
void *dyn_window_open(const char *title,int32_t width,int32_t height){(void)title;(void)width;(void)height;return 0;}
void dyn_window_close(void *h){(void)h;}
int32_t dyn_window_poll(void *h,dyn_window_frame *f){(void)h;memset(f,0,sizeof(*f));f->width=20;f->height=30;return 1;}
int32_t dyn_window_current(void *h){(void)h;return 0;}
int32_t dyn_window_swap(void *h){(void)h;return 0;}
void *dyn_window_proc(const char *s){(void)s;return 0;}
void dyn_window_listen_events(void *h,int32_t e){(void)h;(void)e;}
int32_t dyn_window_next_event(void *h,dyn_window_event *e){(void)h;(void)e;return 0;}
int32_t dyn_window_wake(void *h){(void)h;return 0;}
void dyn_window_composition_get(void *h,dyn_window_composition *c){(void)h;(void)c;}
uint32_t dyn_window_clipboard_get(void *h,const uint8_t **p){(void)h;(void)p;return 0;}
void dyn_window_set_text_input(void *h,int32_t e,int32_t x,int32_t y,int32_t w,int32_t z){(void)h;(void)e;(void)x;(void)y;(void)w;(void)z;}
void dyn_window_desktop_take(void *h,dyn_window_desktop *d){(void)h;(void)d;}
void dyn_window_set_clipboard(void *h,const uint8_t *p,uint32_t n){(void)h;(void)p;(void)n;}
void dyn_window_request_paste(void *h){(void)h;}
void dyn_window_set_cursor(void *h,int32_t c){(void)h;(void)c;}
void dyn_window_wait(void *h,int32_t n){(void)h;(void)n;}
static int status=1;
DYN_WINDOW_EXPORT void probe_status(int32_t value){status=value;}
int32_t dyn_window_set_title(void *h,const uint8_t *p,uint32_t n){(void)h;(void)p;(void)n;return status;}
int32_t dyn_window_set_size(void *h,int32_t w,int32_t z){(void)h;(void)w;(void)z;return status;}
int32_t dyn_window_set_swap_interval(void *h,int32_t n){(void)h;(void)n;return status;}
int32_t dyn_window_try_set_clipboard(void *h,const uint8_t *p,uint32_t n){(void)h;(void)p;(void)n;return status;}
void dyn_window_request_paste_snapshot(void *h){(void)h;}
int32_t dyn_window_paste_pending(void *h){(void)h;return 0;}
int32_t dyn_window_paste_status(void *h){(void)h;return status;}
static int calls;
DYN_WINDOW_EXPORT int32_t probe_calls(void){return calls;}
int32_t dyn_window_set_surrounding_text(void *handle,const uint8_t *text,uint32_t length,uint32_t cursor,uint32_t anchor,uint64_t token,uint32_t cause){
 calls++;
 if(handle!=(void*)1||!text)return 0;
 if(token==2)return -1;
 if(token==3)return -2;
 if(token==9)return length==0&&cursor==0&&anchor==0&&cause==0?1:0;
 const uint8_t expected[]={0x68,0xc3,0xa9,0xf0,0x9f,0x98,0x80};
 return token==UINT64_C(0x1122334455667788)&&length==7&&cursor==3&&anchor==7&&cause==1&&!memcmp(text,expected,7)?1:0;
}
'''
if not shutil.which('cc'):
    print('SKIP surrounding ABI probe: C compiler unavailable')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-surround-abi-') as directory:
    work=Path(directory)
    (work/'main.dyn').write_text(SOURCE,encoding='utf-8');(work/'probe.c').write_text(C, encoding='utf-8')
    host=work/'host';host.mkdir()
    suffix='.dll' if os.name=='nt' else '.dylib' if sys.platform=='darwin' else '.so'
    library=host/('dyn_window.dll' if os.name=='nt' else 'libdyn_window'+suffix)
    command=['cc','-shared','-fPIC','-std=c11','-Wall','-Wextra','-Werror','-I'+str(ROOT/'vendor/window/native'),str(work/'probe.c'),'-o',str(library)]
    if os.name=='nt': command+=['-Wl,--out-implib,'+str(host/'libdyn_window.dll.a')]
    subprocess.run(command,check=True)
    env=dict(os.environ,DYN_LIBRARY_PATH=str(host))
    for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
        output=host/('test.exe' if os.name=='nt' else 'test')
        subprocess.run([DYN,'build',str(work),*flags,'--quiet','--output',str(output)],env=env,check=True,timeout=180)
        subprocess.run([str(output)],env=env,check=True,timeout=60)
    if sys.platform.startswith('linux') and shutil.which('zig'):
        for target in ('x86_64-windows','aarch64-windows'):
            folder=work/target;folder.mkdir();library=folder/'dyn_window.dll'
            subprocess.run(['zig','cc','-target',target+'-gnu','-shared','-std=c11','-Wall','-Wextra','-Werror','-I'+str(ROOT/'vendor/window/native'),str(work/'probe.c'),'-Wl,--out-implib,'+str(folder/'libdyn_window.dll.a'),'-o',str(library)],check=True,timeout=180)
            output=folder/'test.exe';env=dict(os.environ,DYN_LIBRARY_PATH=str(folder))
            subprocess.run([DYN,'build',str(work),'--release','--target',target,'--quiet','--output',str(output)],env=env,check=True,timeout=180)
            if target=='x86_64-windows' and shutil.which('wine'): subprocess.run(['wine',str(output)],env=env,check=True,timeout=90)
print('PASS surrounding native ABI: UTF8 byte lengths, seventh cause argument, 64-bit token, failure mapping and no invalid calls (debug/O2/O3; Windows cross/Wine)')
