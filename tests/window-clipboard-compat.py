#!/usr/bin/env python3
"""Checked Win32 clipboard production paths, with clipboard ownership isolated by mocks."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'vendor/window/native'
SOURCE = r'''#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
static HGLOBAL offered;
static int fail_open, fail_empty, fail_set, fail_close, opens;
static BOOL WINAPI mock_open(HWND w){(void)w;opens++;return !fail_open;}
static BOOL WINAPI mock_empty(void){return !fail_empty;}
static HANDLE WINAPI mock_set(UINT f,HANDLE m){(void)f;if(fail_set)return NULL;if(offered)GlobalFree(offered);offered=m;return m;}
static HANDLE WINAPI mock_get(UINT f){(void)f;return offered;}
static BOOL WINAPI mock_close(void){return !fail_close;}
#define OpenClipboard mock_open
#define EmptyClipboard mock_empty
#define SetClipboardData mock_set
#define GetClipboardData mock_get
#define CloseClipboard mock_close
#include "win32.c"
static void offer(const WCHAR *s,size_t units){if(offered)GlobalFree(offered);offered=GlobalAlloc(GMEM_MOVEABLE,units*sizeof(WCHAR));void*p=GlobalLock(offered);memcpy(p,s,units*sizeof(WCHAR));GlobalUnlock(offered);}
int main(void){
 Host h={0};desktop_listen(&h.desktop,1);
 assert(dyn_window_paste_status(&h)==-4 && !dyn_window_paste_pending(&h));
 const uint8_t good[]={'a',0xc3,0xa9,0xf0,0x9f,0x98,0x80};
 assert(dyn_window_try_set_clipboard(&h,good,sizeof(good))==1);
 assert(h.desktop.owned_length==sizeof(good));
 int count=opens;
 assert(dyn_window_try_set_clipboard(&h,(const uint8_t*)"a\0b",3)==-3);
 const uint8_t bad[]={0xc0,0x80};assert(dyn_window_try_set_clipboard(&h,bad,2)==-3);
 assert(dyn_window_try_set_clipboard(&h,NULL,1)==-3);
 assert(dyn_window_try_set_clipboard(&h,good,DYN_CLIPBOARD_LIMIT+1)==-2);
 assert(opens==count && h.desktop.owned_length==sizeof(good));
 for(int mode=0;mode<4;mode++){
  fail_open=mode==0;fail_empty=mode==1;fail_set=mode==2;fail_close=mode==3;
  assert(dyn_window_try_set_clipboard(&h,(const uint8_t*)"x",1)==0);
  assert(h.desktop.owned_length==sizeof(good));
 }
 fail_open=fail_empty=fail_set=fail_close=0;
 assert(dyn_window_try_set_clipboard(&h,good,sizeof(good))==1);
 desktop_simple(&h.desktop,DYN_EVENT_WAKE);
 dyn_window_request_paste_snapshot(&h);assert(dyn_window_paste_status(&h)==1);
 assert(h.desktop.received_length==sizeof(good)&&!memcmp(h.desktop.received,good,sizeof(good)));
 dyn_window_event e;assert(desktop_next(&h.desktop,&e)&&e.kind==DYN_EVENT_WAKE);assert(!desktop_next(&h.desktop,&e));
 dyn_window_request_paste(&h);assert(desktop_next(&h.desktop,&e)&&e.kind==DYN_EVENT_CLIPBOARD&&e.button&&e.text_length==sizeof(good));
 fail_open=1;dyn_window_request_paste_snapshot(&h);assert(dyn_window_paste_status(&h)==0&&h.desktop.received_length==sizeof(good));fail_open=0;
 WCHAR invalid[]={0xd800,0};offer(invalid,2);dyn_window_request_paste_snapshot(&h);assert(dyn_window_paste_status(&h)==-3&&h.desktop.received_length==sizeof(good));
 WCHAR*large=calloc(DYN_CLIPBOARD_LIMIT+2,sizeof(WCHAR));for(unsigned i=0;i<DYN_CLIPBOARD_LIMIT+1;i++)large[i]='a';offer(large,DYN_CLIPBOARD_LIMIT+2);free(large);
 dyn_window_request_paste_snapshot(&h);assert(dyn_window_paste_status(&h)==-2&&h.desktop.received_length==sizeof(good));
 uint8_t*exact=malloc(DYN_CLIPBOARD_LIMIT);memset(exact,'q',DYN_CLIPBOARD_LIMIT);
 assert(dyn_window_try_set_clipboard(&h,exact,DYN_CLIPBOARD_LIMIT)==1);dyn_window_request_paste_snapshot(&h);
 assert(dyn_window_paste_status(&h)==1&&h.desktop.received_length==DYN_CLIPBOARD_LIMIT&&!memcmp(h.desktop.received,exact,DYN_CLIPBOARD_LIMIT));free(exact);
 assert(dyn_window_try_set_clipboard(&h,NULL,0)==1);dyn_window_request_paste_snapshot(&h);assert(dyn_window_paste_status(&h)==1&&!h.desktop.received_length);assert(!desktop_next(&h.desktop,&e));
 dyn_window_request_paste(&h);assert(desktop_next(&h.desktop,&e)&&e.kind==DYN_EVENT_CLIPBOARD&&e.button&&!e.text_length);
 GlobalFree(offered);puts("PASS checked Win32 clipboard: failures, UTF8/UTF16, capacity, empty, preserved snapshots and event isolation");return 0;
}
'''
def zig_path():
    candidate=shutil.which('zig')
    candidates=([Path(candidate).resolve()] if candidate else [])
    candidates+=sorted((Path.home()/'.local/share/mise/installs/zig').glob('*/zig'))
    for item in candidates:
        if item.is_file() and os.access(item,os.X_OK):
            try:
                subprocess.run([str(item),'version'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
                return str(item)
            except (OSError,subprocess.SubprocessError):pass
    return None
with tempfile.TemporaryDirectory(prefix='dyn-clipboard-compat-') as directory:
    work=Path(directory);source=work/'probe.c';source.write_text(SOURCE)
    zig=zig_path()
    if zig:
        for target in ('x86_64-windows-gnu','aarch64-windows-gnu'):
            subprocess.run([zig,'cc','-target',target,'-std=c11','-Wall','-Wextra','-Werror','-I'+str(NATIVE),'-c',str(source),'-o',str(work/(target+'.o'))],check=True,timeout=180)
        print('PASS strict Windows x64/ARM64 compilation')
        if shutil.which('wine'):
            output=work/'probe.exe'
            subprocess.run([zig,'cc','-target','x86_64-windows-gnu','-I'+str(NATIVE),str(source),'-luser32','-lgdi32','-lopengl32','-limm32','-o',str(output)],check=True,timeout=180)
            subprocess.run(['wine',str(output)],check=True,timeout=90)
        else:print('SKIP Wine runtime unavailable')
    else:print('SKIP Windows C toolchain unavailable')
print('SKIP Cocoa live qualification: requires macOS SDK/runtime')
