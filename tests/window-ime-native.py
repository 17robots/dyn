#!/usr/bin/env python3
"""Owned native IME/clipboard event payloads and production Win32 IMM adapters."""
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'vendor/window/native'
COMMON = r'''#include "desktop_common.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
static Desktop desktop;
int main(void) {
  assert(sizeof(dyn_window_event)==312 && sizeof(dyn_window_composition)==272);
  assert(offsetof(dyn_window_composition,cursor_begin)==260);
  desktop_listen(&desktop,1);
  dyn_window_composition composition={0};
  const uint8_t astral[]={0xf0,0x9f,0x98,0x80,'x'};
  composition_store(&composition,astral,sizeof(astral),1,5);
  assert(composition.cursor_begin==0 && composition.cursor_end==5);
  composition_changed(&desktop,&composition);
  assert(desktop.pending.keys & DYN_KEY_IME);
  composition_store(&composition,(const uint8_t *)"new",3,-1,-1);
  composition_changed(&desktop,&composition);
  memset(&composition,0,sizeof(composition));
  composition_changed(&desktop,&composition);
  dyn_window_event event;
  assert(desktop_next(&desktop,&event) && event.kind==DYN_EVENT_COMPOSITION && event.text_length==5 && event.x==0 && event.y==5 && event.width==1 && !memcmp(event.text,astral,5));
  assert(desktop_next(&desktop,&event) && event.text_length==3 && !memcmp(event.text,"new",3) && event.x==-1 && event.y==-1);
  assert(desktop_next(&desktop,&event) && event.text_length==0 && !event.width);
  uint8_t long_text[260];memset(long_text,'a',255);memcpy(long_text+255,astral,4);long_text[259]='z';
  composition_store(&composition,long_text,sizeof(long_text),259,1000);
  assert(composition.text_length==255 && composition.cursor_begin==255 && composition.cursor_end==255);
  memset(desktop.received,'a',255);
  memcpy(desktop.received+255,astral,4);memset(desktop.received+259,'b',300);
  desktop.received_length=559;desktop_deliver(&desktop);
  memset(desktop.received,'!',559);desktop.received_length=0;desktop_deliver(&desktop);
  assert(desktop_next(&desktop,&event) && event.kind==DYN_EVENT_CLIPBOARD && event.x==0 && event.width==559 && event.text_length==255 && !event.button && event.text[0]=='a');
  assert(desktop_next(&desktop,&event) && event.x==255 && event.text_length==256 && !event.button && !memcmp(event.text,astral,4));
  assert(desktop_next(&desktop,&event) && event.x==511 && event.text_length==48 && event.button==1 && event.text[0]=='b');
  assert(desktop_next(&desktop,&event) && event.x==0 && event.width==0 && event.text_length==0 && event.button==1);
  assert(!desktop_next(&desktop,&event));
  memset(desktop.received,'x',sizeof(desktop.received));desktop.received_length=sizeof(desktop.received);desktop_deliver(&desktop);
  for(unsigned i=0;i<DYN_EVENT_CAPACITY;i++) assert(desktop_next(&desktop,&event) && event.kind==DYN_EVENT_CLIPBOARD && !event.button);
  assert(desktop_next(&desktop,&event) && event.kind==DYN_EVENT_OVERFLOW && event.dropped==128);
  puts("PASS native owned composition/clipboard payloads, UTF8 cursor/clipping, empty replies and overflow");
}
'''
WINDOWS = r'''#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <imm.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
static WCHAR sample[256];static int sample_units,cursor_units;
static DWORD association;static COMPOSITIONFORM composition_form;static CANDIDATEFORM candidate_form;static int cancelled;
static HIMC WINAPI mock_context(HWND window){(void)window;return(HIMC)(uintptr_t)1;}
static BOOL WINAPI mock_release(HWND window,HIMC context){(void)window;(void)context;return TRUE;}
static BOOL WINAPI mock_associate(HWND window,HIMC context,DWORD flags){(void)window;(void)context;association=flags;return TRUE;}
static BOOL WINAPI mock_notify(HIMC context,DWORD action,DWORD index,DWORD value){(void)context;(void)index;(void)value;cancelled=action==NI_COMPOSITIONSTR;return TRUE;}
static BOOL WINAPI mock_composition(HIMC context,LPCOMPOSITIONFORM form){(void)context;composition_form=*form;return TRUE;}
static BOOL WINAPI mock_candidate(HIMC context,LPCANDIDATEFORM form){(void)context;candidate_form=*form;return TRUE;}
static LONG WINAPI mock_get(HIMC context,DWORD index,LPVOID output,DWORD capacity){
 (void)context;if(index==GCS_CURSORPOS)return cursor_units;
 if(index==GCS_COMPSTR){DWORD length=(DWORD)sample_units*sizeof(WCHAR);if(output){DWORD copied=capacity<length?capacity:length;memcpy(output,sample,copied);}return(LONG)length;}return 0;
}
#define ImmGetContext mock_context
#define ImmReleaseContext mock_release
#define ImmAssociateContextEx mock_associate
#define ImmNotifyIME mock_notify
#define ImmSetCompositionWindow mock_composition
#define ImmSetCandidateWindow mock_candidate
#define ImmGetCompositionStringW mock_get
#include "win32.c"
static void empty(Host *h){dyn_window_event event;while(desktop_next(&h->desktop,&event)){}memset(&h->desktop.pending,0,sizeof(h->desktop.pending));}
int main(void){
 Host h={0};h.window=CreateWindowExW(0,L"STATIC",L"IME adapter probe",WS_OVERLAPPEDWINDOW,0,0,80,80,NULL,NULL,GetModuleHandleW(NULL),NULL);
 assert(h.window);SetWindowLongPtrW(h.window,GWLP_USERDATA,(LONG_PTR)&h);desktop_listen(&h.desktop,1);
 /* Explicit disable is meaningful even before the first enable. */
 dyn_window_set_text_input(&h,0,0,0,0,0);assert(association==0);
 procedure(h.window,WM_CHAR,'x',1);assert(!h.desktop.event_count && !h.desktop.pending.text_length);
 dyn_window_set_text_input(&h,1,10,20,30,40);assert(association==IACE_DEFAULT);
 assert(composition_form.ptCurrentPos.x==10 && composition_form.ptCurrentPos.y==20);
 assert(candidate_form.ptCurrentPos.y==60 && candidate_form.rcArea.right==40 && candidate_form.rcArea.bottom==60);
 /* Longer valid preedit must be clipped, not fail UTF16->UTF8 conversion. */
 for(int i=0;i<200;i++)sample[i]=0x4e00;sample_units=200;cursor_units=200;
 procedure(h.window,WM_IME_COMPOSITION,0,GCS_COMPSTR);
 assert(h.composition.active && h.composition.text_length==255 && h.composition.cursor_begin==255);
 sample[0]=0xd83d;sample[1]=0xde00;sample_units=2;cursor_units=1;
 procedure(h.window,WM_IME_COMPOSITION,0,GCS_COMPSTR);
 assert(h.composition.text_length==4 && h.composition.cursor_begin==0);
 procedure(h.window,WM_CHAR,'a',1);procedure(h.window,WM_IME_ENDCOMPOSITION,0,0);
 dyn_window_event event;
 assert(desktop_next(&h.desktop,&event) && event.kind==DYN_EVENT_COMPOSITION && event.text_length==255 && event.width==1);
 assert(desktop_next(&h.desktop,&event) && event.kind==DYN_EVENT_COMPOSITION && event.text_length==4 && event.x==0);
 assert(desktop_next(&h.desktop,&event) && event.kind==DYN_EVENT_TEXT && event.text[0]=='a');
 assert(desktop_next(&h.desktop,&event) && event.kind==DYN_EVENT_COMPOSITION && !event.width);
 empty(&h);sample[0]='x';sample_units=1;cursor_units=1;procedure(h.window,WM_IME_COMPOSITION,0,GCS_COMPSTR);
 h.desktop.pending.keys &= ~(uint32_t)DYN_KEY_IME;
 dyn_window_set_text_input(&h,0,0,0,0,0);assert(cancelled && association==0 && !h.composition.active);
 assert(!(h.desktop.pending.keys & DYN_KEY_IME));
 procedure(h.window,WM_KEYDOWN,VK_BACK,1);
 assert((h.desktop.pending.keys & DYN_KEY_BACKSPACE) && !(h.desktop.pending.keys & DYN_KEY_IME));empty(&h);
 dyn_window_set_text_input(&h,1,0,0,0,0);procedure(h.window,WM_IME_COMPOSITION,0,GCS_COMPSTR);
 assert(h.desktop.pending.keys & DYN_KEY_IME);
 dyn_window_set_text_input(&h,0,0,0,0,0);assert(h.desktop.pending.keys & DYN_KEY_IME);empty(&h);
 procedure(h.window,WM_IME_COMPOSITION,0,GCS_COMPSTR);procedure(h.window,WM_CHAR,'q',1);
 assert(!h.composition.active && !h.desktop.pending.text_length && !h.desktop.event_count);
 const uint8_t text[]={ 'c','l','i','p',' ',0xe2,0x9c,0x93 };
 dyn_window_set_clipboard(&h,text,sizeof(text));dyn_window_request_paste(&h);dyn_window_frame frame;dyn_window_poll(&h,&frame);
 int found=0;while(dyn_window_next_event(&h,&event)){if(event.kind==DYN_EVENT_CLIPBOARD){assert(event.button && event.text_length==sizeof(text)&&!memcmp(event.text,text,sizeof(text)));found=1;}}
 assert(found);
 dyn_window_set_text_input(&h,1,0,0,0,0);empty(&h);
 procedure(h.window,WM_CHAR,0xd83d,1);assert(h.high_surrogate);
 dyn_window_set_text_input(&h,0,0,0,0,0);dyn_window_set_text_input(&h,1,0,0,0,0);empty(&h);
 procedure(h.window,WM_CHAR,0xde00,1);assert(!h.high_surrogate && !h.desktop.event_count && !h.desktop.pending.text_length);
 DestroyWindow(h.window);
 puts("PASS Win32 production IMM adapter: candidate rect, bounded Unicode preedit, snapshot order, disable, and clipboard bytes");return 0;
}
'''
WAYLAND = r'''#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <wayland-client.h>
#include <xkbcommon/xkbcommon.h>
#include "text-input-unstable-v3-client-protocol.h"
static int enables,disables,commits;static int32_t rectangle[4];static xkb_keysym_t symbol=XKB_KEY_a;
static void mock_enable(struct zwp_text_input_v3*t){(void)t;enables++;}
static void mock_disable(struct zwp_text_input_v3*t){(void)t;disables++;}
static void mock_type(struct zwp_text_input_v3*t,uint32_t h,uint32_t p){(void)t;(void)h;(void)p;}
static void mock_cursor(struct zwp_text_input_v3*t,int32_t x,int32_t y,int32_t w,int32_t h){(void)t;rectangle[0]=x;rectangle[1]=y;rectangle[2]=w;rectangle[3]=h;}
static void mock_commit(struct zwp_text_input_v3*t){(void)t;commits++;}
static int mock_flush(struct wl_display*d){(void)d;return 0;}
static xkb_keysym_t mock_sym(struct xkb_state*s,xkb_keycode_t k){(void)s;(void)k;return symbol;}
static int mock_mod(struct xkb_state*s,const char*n,enum xkb_state_component c){(void)s;(void)n;(void)c;return 0;}
static int mock_utf8(struct xkb_state*s,xkb_keycode_t k,char*b,size_t n){(void)s;(void)k;if(n>1){b[0]='a';b[1]=0;}return 1;}
#define zwp_text_input_v3_enable mock_enable
#define zwp_text_input_v3_disable mock_disable
#define zwp_text_input_v3_set_content_type mock_type
#define zwp_text_input_v3_set_cursor_rectangle mock_cursor
#define zwp_text_input_v3_commit mock_commit
#define wl_display_flush mock_flush
#define xkb_state_key_get_one_sym mock_sym
#define xkb_state_mod_name_is_active mock_mod
#define xkb_state_key_get_utf8 mock_utf8
#include "wayland.c"
static void drain(Host*h){dyn_window_event event;while(desktop_next(&h->desktop,&event)){}memset(&h->desktop.pending,0,sizeof(h->desktop.pending));}
int main(void){
 Host h={0};h.scale=2;h.surface=(struct wl_surface*)(uintptr_t)1;h.state=(struct xkb_state*)(uintptr_t)1;desktop_listen(&h.desktop,1);
 press(&h,0);assert(h.desktop.pending.text_length==1);drain(&h);
 dyn_window_set_text_input(&h,0,0,0,0,0);press(&h,0);assert(!h.desktop.pending.text_length);drain(&h);
 h.text_input=(struct zwp_text_input_v3*)(uintptr_t)1;
 dyn_window_set_text_input(&h,1,10,20,30,40);assert(enables==0);
 text_enter(&h,NULL,h.surface);assert(enables==1 && commits==1 && rectangle[0]==5 && rectangle[3]==20);
 dyn_window_set_text_input(&h,1,12,22,30,40);assert(enables==1 && commits==2 && rectangle[0]==6 && rectangle[1]==11);
 press(&h,0);assert(!h.desktop.pending.text_length && !h.desktop.event_count);
 text_preedit(&h,NULL,"abc",1,2);text_commit(&h,NULL,"first");text_commit(&h,NULL,"last");text_done(&h,NULL,99);
 dyn_window_event event;
 assert(desktop_next(&h.desktop,&event) && event.kind==DYN_EVENT_TEXT && event.text_length==4 && !memcmp(event.text,"last",4));
 assert(desktop_next(&h.desktop,&event) && event.kind==DYN_EVENT_COMPOSITION && event.text_length==3 && event.x==1 && event.y==2 && event.width);
 assert(enables==1 && commits==2);
 text_commit(&h,NULL,"!");text_done(&h,NULL,100);
 assert(desktop_next(&h.desktop,&event) && event.kind==DYN_EVENT_COMPOSITION && !event.width);
 assert(desktop_next(&h.desktop,&event) && event.kind==DYN_EVENT_TEXT && event.text_length==1 && event.text[0]=='!');
 char preedit[260];memset(preedit,'a',255);memcpy(preedit+255,"\xf0\x9f\x98\x80",4);preedit[259]=0;
 text_preedit(&h,NULL,preedit,259,259);text_done(&h,NULL,100);
 assert(desktop_next(&h.desktop,&event) && event.kind==DYN_EVENT_COMPOSITION && event.text_length==255 && event.x==255 && event.y==255);
 char large[4098];memset(large,'x',4097);large[4097]=0;text_commit(&h,NULL,large);text_done(&h,NULL,100);
 assert(desktop_next(&h.desktop,&event) && event.kind==DYN_EVENT_COMPOSITION && !event.width);
 assert(desktop_next(&h.desktop,&event) && event.kind==DYN_EVENT_OVERFLOW && event.dropped==1);
 text_preedit(&h,NULL,"stale",5,5);text_commit(&h,NULL,"stale");text_leave(&h,NULL,h.surface);drain(&h);text_done(&h,NULL,100);
 assert(!h.desktop.event_count && !h.desktop.pending.text_length && !h.composition.active);
 text_enter(&h,NULL,h.surface);assert(enables==2);
 composition_store(&h.composition,(const uint8_t*)"live",4,4,4);
 h.desktop.pending.keys &= ~(uint32_t)DYN_KEY_IME;
 dyn_window_set_text_input(&h,0,0,0,0,0);assert(disables==1 && !(h.desktop.pending.keys & DYN_KEY_IME));
 symbol=XKB_KEY_BackSpace;press(&h,0);symbol=XKB_KEY_a;
 assert((h.desktop.pending.keys & DYN_KEY_BACKSPACE) && !(h.desktop.pending.keys & DYN_KEY_IME));
 dyn_window_set_text_input(&h,0,0,0,0,0);assert(disables==1);
 dyn_window_set_text_input(&h,1,0,0,0,0);
 composition_store(&h.composition,(const uint8_t*)"live",4,4,4);composition_changed(&h.desktop,&h.composition);
 dyn_window_set_text_input(&h,0,0,0,0,0);assert(h.desktop.pending.keys & DYN_KEY_IME);
 drain(&h);h.receive_fd=123;h.source=(struct wl_data_source*)(uintptr_t)1;
 memcpy(h.desktop.received,"partial",7);h.desktop.received_length=7;
 memcpy(h.desktop.owned,"new",3);h.desktop.owned_length=3;
 dyn_window_request_paste(&h);
 assert(h.receive_fd==123 && h.desktop.received_length==7 && !memcmp(h.desktop.received,"partial",7));
 assert(desktop_next(&h.desktop,&event) && event.kind==DYN_EVENT_OVERFLOW && event.dropped==1);
 assert(!desktop_next(&h.desktop,&event));
 puts("PASS production Wayland IME transaction order, enable transitions, candidate scale, UTF8 bounds, disable and local-text suppression");
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-ime-native-') as directory:
    work=Path(directory)
    common=work/'common.c';common.write_text(COMMON)
    cc=shlex.split(os.environ.get('CC','cc'))
    if not cc or not shutil.which(cc[0]): cc=[]
    if cc:
        output=work/('common.exe' if os.name=='nt' else 'common')
        subprocess.run([*cc,'-std=c11','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(common),'-o',str(output)],check=True)
        subprocess.run([str(output)],check=True,timeout=30)
    else:
        print('SKIP native common ABI/ownership contracts: C compiler unavailable')
    if sys.platform.startswith('linux') and cc and shutil.which('wayland-scanner') and shutil.which('pkg-config'):
        available = subprocess.run(['pkg-config','--exists','wayland-client','wayland-egl','wayland-cursor','xkbcommon','egl','wayland-protocols']).returncode == 0
        if available:
            subprocess.run([sys.executable,str(NATIVE/'build.py'),'--output',str(work/'libdyn_window.so')],check=True,timeout=120)
            probe=work/'wayland-probe.c';probe.write_text(WAYLAND)
            flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','wayland-client','wayland-egl','wayland-cursor','xkbcommon','egl'],text=True))
            output=work/'wayland-probe'
            subprocess.run([*cc,'-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror','-I'+str(NATIVE),'-I'+str(work),str(probe),str(work/'xdg-shell-protocol.c'),str(work/'text-input-unstable-v3-protocol.c'),*flags,'-o',str(output)],check=True,timeout=120)
            subprocess.run([str(output)],check=True,timeout=30)
    if sys.platform.startswith('linux') and shutil.which('zig'):
        probe=work/'windows.c';probe.write_text(WINDOWS)
        for target in ('x86_64-windows-gnu','aarch64-windows-gnu'):
            subprocess.run(['zig','cc','-target',target,'-std=c11','-Wall','-Wextra','-Werror','-I'+str(NATIVE),'-c',str(probe),'-o',str(work/(target+'.o'))],check=True,timeout=120)
        if shutil.which('wine') and os.environ.get('DISPLAY'):
            output=work/'windows.exe'
            subprocess.run(['zig','cc','-target','x86_64-windows-gnu','-I'+str(NATIVE),str(probe),'-luser32','-lgdi32','-lopengl32','-limm32','-o',str(output)],check=True,timeout=180)
            subprocess.run(['wine',str(output)],check=True,timeout=60)
    if os.name=='nt' and cc:
        probe=work/'windows.c';probe.write_text(WINDOWS);output=work/'windows.exe'
        subprocess.run([*cc,'-std=c11','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(probe),'-luser32','-lgdi32','-lopengl32','-limm32','-o',str(output)],check=True,timeout=180)
        subprocess.run([str(output)],check=True,timeout=60)
print('PASS native IME payload and adapter contracts; native Cocoa runtime remains unqualified')
