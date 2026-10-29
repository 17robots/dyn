#!/usr/bin/env python3
"""Production IMM surrounding document feed and selected-range reconversion."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'vendor/window/native'
SOURCE = r'''#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <imm.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
static WCHAR sample[4097];static LONG sample_bytes;static int defaults;
static HIMC WINAPI mock_context(HWND w){(void)w;return (HIMC)(uintptr_t)1;}
static BOOL WINAPI mock_release(HWND w,HIMC c){(void)w;(void)c;return TRUE;}
static LONG WINAPI mock_get(HIMC c,DWORD index,LPVOID out,DWORD capacity){
 (void)c;if(index!=GCS_RESULTSTR)return 0;
 if(out && sample_bytes>=0 && (DWORD)sample_bytes<=capacity)memcpy(out,sample,(size_t)sample_bytes);
 return sample_bytes;
}
static LRESULT WINAPI mock_default(HWND w,UINT m,WPARAM a,LPARAM b){(void)w;(void)m;(void)a;(void)b;defaults++;return 123;}
#define ImmGetContext mock_context
#define ImmReleaseContext mock_release
#define ImmGetCompositionStringW mock_get
#define DefWindowProcW mock_default
#include "win32.c"
static const uint8_t original[]={'a',0xc3,0xa9,0xf0,0x9f,0x98,0x80,'z'};
static void drain(Host*h){dyn_window_event e;while(desktop_next(&h->desktop,&e)){}memset(&h->desktop.pending,0,sizeof(h->desktop.pending));}
static void publish(Host*h,uint64_t token){assert(dyn_window_set_surrounding_text(h,original,sizeof(original),7,3,token,0)==1);}
static RECONVERTSTRING *request(Host*h,uint8_t*storage){
 LRESULT size=procedure(h->window,WM_IME_REQUEST,IMR_RECONVERTSTRING,0);
 assert(size==sizeof(RECONVERTSTRING)+12);
 RECONVERTSTRING*r=(RECONVERTSTRING*)storage;memset(storage,0xaa,128);r->dwSize=(DWORD)size;
 assert(procedure(h->window,WM_IME_REQUEST,IMR_RECONVERTSTRING,(LPARAM)r)==size);
 assert(r->dwVersion==0 && r->dwStrLen==5 && r->dwStrOffset==sizeof(*r));
 assert(r->dwCompStrOffset==4 && r->dwCompStrLen==2 && r->dwTargetStrOffset==4 && r->dwTargetStrLen==2);
 const WCHAR expected[]={'a',0xe9,0xd83d,0xde00,'z',0};
 assert(!memcmp(storage+sizeof(*r),expected,sizeof(expected)));return r;
}
static void start(Host*h){procedure(h->window,WM_IME_STARTCOMPOSITION,0,0);assert(h->reconvert_active);drain(h);}
static void result(Host*h){int before=defaults;assert(procedure(h->window,WM_IME_COMPOSITION,0,GCS_RESULTSTR)==0);assert(defaults==before);}
static void end(Host*h){procedure(h->window,WM_IME_ENDCOMPOSITION,0,0);drain(h);}
static void overflow(Host*h){dyn_window_event e;assert(desktop_next(&h->desktop,&e)&&e.kind==DYN_EVENT_OVERFLOW);assert(!desktop_next(&h->desktop,&e));assert(!h->desktop.pending.text_length);}
int main(void){
 Host h={0};h.window=CreateWindowExW(0,L"STATIC",L"surrounding",WS_OVERLAPPEDWINDOW,0,0,80,80,NULL,NULL,GetModuleHandleW(NULL),NULL);
 assert(h.window);SetWindowLongPtrW(h.window,GWLP_USERDATA,(LONG_PTR)&h);h.text_input=1;
 assert(!dyn_window_set_surrounding_text(&h,original,sizeof(original),7,3,1,0));desktop_listen(&h.desktop,1);publish(&h,UINT64_C(0x1122334455667788));
 Surrounding saved=h.desktop.surrounding;
 assert(!dyn_window_set_surrounding_text(&h,original,sizeof(original),4,3,2,0));assert(!memcmp(&saved,&h.desktop.surrounding,sizeof(saved)));
 assert(!dyn_window_set_surrounding_text(&h,original,sizeof(original),7,3,2,2));
 uint8_t buffer[128];RECONVERTSTRING*r=request(&h,buffer);
 /* DOCUMENTFEED does not arm another correction. Bounded reply failures write nothing. */
 h.reconvert_pending=0;r->dwSize=sizeof(*r);RECONVERTSTRING header=*r;
 assert(!procedure(h.window,WM_IME_REQUEST,IMR_DOCUMENTFEED,(LPARAM)r));assert(!memcmp(r,&header,sizeof(header)));
 r->dwSize=128;assert(procedure(h.window,WM_IME_REQUEST,IMR_DOCUMENTFEED,(LPARAM)r)>0 && !h.reconvert_pending);
 r=request(&h,buffer);RECONVERTSTRING valid=*r;
 r->dwCompStrOffset=6;r->dwCompStrLen=1;r->dwTargetStrOffset=6;r->dwTargetStrLen=1;
 assert(!procedure(h.window,WM_IME_REQUEST,IMR_CONFIRMRECONVERTSTRING,(LPARAM)r));assert(h.reconvert_start==3&&h.reconvert_end==7);*r=valid;
 r->dwStrOffset=0xffffffff;assert(!procedure(h.window,WM_IME_REQUEST,IMR_CONFIRMRECONVERTSTRING,(LPARAM)r));*r=valid;
 buffer[sizeof(*r)]='x';assert(!procedure(h.window,WM_IME_REQUEST,IMR_CONFIRMRECONVERTSTRING,(LPARAM)r));buffer[sizeof(*r)]='a';
 /* IME expands selection to include é; target stays inside composition. */
 r->dwCompStrOffset=2;r->dwCompStrLen=3;assert(procedure(h.window,WM_IME_REQUEST,IMR_CONFIRMRECONVERTSTRING,(LPARAM)r));
 assert(h.reconvert_start==1 && h.reconvert_end==7);start(&h);
 sample[0]=0x4e00;sample[1]=0xd83d;sample[2]=0xde00;sample_bytes=6;result(&h);
 dyn_window_event e;assert(desktop_next(&h.desktop,&e)&&e.kind==DYN_EVENT_EDIT&&e.x==1&&e.y==7&&e.width==7&&e.button&&e.text_length==7);
 assert(e.key==0x55667788 && e.modifiers==0x11223344 && !memcmp(e.text,"\xe4\xb8\x80\xf0\x9f\x98\x80",7));
 assert(!desktop_next(&h.desktop,&e)&&!h.desktop.pending.text_length);
 assert(!dyn_window_set_surrounding_text(&h,original,sizeof(original),7,3,saved.token,0));
 result(&h);overflow(&h);end(&h);
 end(&h);publish(&h,40);request(&h,buffer);start(&h);sample_bytes=0;result(&h);
 assert(desktop_next(&h.desktop,&e)&&e.kind==DYN_EVENT_EDIT&&e.x==3&&e.y==7&&e.width==0&&e.text_length==0&&e.button);end(&h);
 /* Cancellation preserves original bytes; changed source rejects active results. */
 publish(&h,2);request(&h,buffer);start(&h);end(&h);assert(h.desktop.consumed_token==40);
 publish(&h,3);request(&h,buffer);start(&h);publish(&h,4);result(&h);overflow(&h);end(&h);
 publish(&h,5);request(&h,buffer);publish(&h,6);start(&h);result(&h);overflow(&h);end(&h);
 /* Focus loss/disable cancels pending reconversion without allowing its late
  * result to fall through the ordinary default WM_CHAR insertion path. */
 for(int mode=0;mode<2;mode++){
  publish(&h,(uint64_t)(50+mode*2));request(&h,buffer);
  if(mode==0)procedure(h.window,WM_KILLFOCUS,0,0);
  else dyn_window_set_text_input(&h,0,0,0,0,0);
  assert(h.reconvert_pending && !h.reconvert.token);drain(&h);
  publish(&h,(uint64_t)(51+mode*2));dyn_window_set_text_input(&h,1,0,0,0,0);
  assert(!procedure(h.window,WM_IME_REQUEST,IMR_RECONVERTSTRING,0));
  start(&h);sample[0]='x';sample_bytes=2;result(&h);overflow(&h);end(&h);
  assert(h.desktop.consumed_token==40);
 }
 /* Entire results fail closed for unpaired UTF16, NUL, truncation and capacity. */
 for(int mode=0;mode<4;mode++){
  publish(&h,(uint64_t)(10+mode));request(&h,buffer);start(&h);
  sample[0]=mode==0?0xd83d:mode==1?0:'x';sample_bytes=mode==2?8194:mode==3?1:2;
  result(&h);overflow(&h);end(&h);
 }
 /* Atomic preflight retains existing events and emits no partial correction. */
 publish(&h,20);request(&h,buffer);start(&h);
 for(unsigned i=0;i<DYN_EVENT_CAPACITY-1;i++)desktop_simple(&h.desktop,DYN_EVENT_WAKE);
 for(int i=0;i<300;i++)sample[i]='x';sample_bytes=600;result(&h);
 for(unsigned i=0;i<DYN_EVENT_CAPACITY-1;i++)assert(desktop_next(&h.desktop,&e)&&e.kind==DYN_EVENT_WAKE);
 overflow(&h);end(&h);
 /* Collapsed reconversion is explicit rejection, while document feed works. */
 assert(dyn_window_set_surrounding_text(&h,original,sizeof(original),3,3,30,0)==1);
 assert(!procedure(h.window,WM_IME_REQUEST,IMR_RECONVERTSTRING,0));assert(procedure(h.window,WM_IME_REQUEST,IMR_DOCUMENTFEED,0)>0);
 DestroyWindow(h.window);puts("PASS Win32 production document feed and selected reconversion: UTF16 ranges, confirmation, owned atomic edits, stale tokens, cancellation and malformed results");return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-surround-win32-') as directory:
    work=Path(directory);source=work/'probe.c';source.write_text(SOURCE)
    if sys.platform.startswith('linux') and shutil.which('zig'):
        for target in ('x86_64-windows-gnu','aarch64-windows-gnu'):
            subprocess.run(['zig','cc','-target',target,'-std=c11','-Wall','-Wextra','-Werror','-I'+str(NATIVE),'-c',str(source),'-o',str(work/(target+'.o'))],check=True,timeout=180)
        if shutil.which('wine'):
            output=work/'probe.exe'
            subprocess.run(['zig','cc','-target','x86_64-windows-gnu','-I'+str(NATIVE),str(source),'-luser32','-lgdi32','-lopengl32','-limm32','-o',str(output)],check=True,timeout=180)
            subprocess.run(['wine',str(output)],check=True,timeout=90)
    elif os.name=='nt' and shutil.which('cc'):
        output=work/'probe.exe'
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(source),'-luser32','-lgdi32','-lopengl32','-limm32','-o',str(output)],check=True,timeout=180)
        subprocess.run([str(output)],check=True,timeout=90)
    else: print('SKIP Win32 surrounding oracle: Windows C toolchain unavailable')
