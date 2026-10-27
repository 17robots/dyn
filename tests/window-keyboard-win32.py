#!/usr/bin/env python3
"""Production Win32 queued character snapshots with controlled keyboard APIs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'vendor/window/native'
SOURCE=r'''#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
static void *host;
static BYTE keyboard[256];
static HKL layout=(HKL)(uintptr_t)1;
static int mode, unavailable, snapshots;
static LONG_PTR WINAPI mock_host(HWND w,int index){(void)w;(void)index;return (LONG_PTR)host;}
static SHORT WINAPI mock_state(int key){return keyboard[key]&0x80?(SHORT)0x8000:0;}
static BOOL WINAPI mock_keyboard(PBYTE state){memcpy(state,keyboard,256);return !unavailable;}
static HKL WINAPI mock_layout(DWORD thread){(void)thread;return layout;}
static LRESULT WINAPI mock_default(HWND w,UINT m,WPARAM a,LPARAM b){(void)w;(void)m;(void)a;(void)b;return 0;}
static int WINAPI mock_translate(UINT key,UINT scan,const BYTE*state,LPWSTR out,int capacity,UINT flags,HKL current){
 (void)key;assert(scan==5);assert(flags==4);assert(current==layout);
 if(capacity==4){out[0]='4';return 1;}
 assert(capacity==8);snapshots++;
 switch(mode){
 case 1:out[0]=0xd83d;out[1]=0xde00;return 2;
 case 2:out[0]='a';out[1]='b';return 2;
 case 3:out[0]='^';return -1;
 case 4:out[0]=0xd800;return 1;
 case 5:out[0]=0xdc00;return 1;
 case 6:out[0]=0xd83d;out[1]=0xde00;out[2]='a';return 3;
 default:if(state[VK_CONTROL]&0x80){out[0]=state[VK_MENU]&0x80?0x20ac:4;return 1;}out[0]=current==(HKL)(uintptr_t)2?0x20ac:(state[VK_SHIFT]&0x80?'$':'4');return 1;
 }
}
#define GetWindowLongPtrW mock_host
#define GetKeyState mock_state
#define GetKeyboardState mock_keyboard
#define GetKeyboardLayout mock_layout
#define ToUnicodeEx mock_translate
#define DefWindowProcW mock_default
#include "win32.c"
static LPARAM message(unsigned count){return (LPARAM)((5u<<16)|count);}
int main(void){
 Host h={0};host=&h;desktop_listen(&h.desktop,1);
 keyboard[VK_SHIFT]=0x80;
 procedure(NULL,WM_KEYDOWN,'4',message(3));
 keyboard[VK_SHIFT]=0;layout=(HKL)(uintptr_t)2;
 procedure(NULL,WM_KEYUP,'4',message(1));
 layout=(HKL)(uintptr_t)1;
 dyn_window_event event;
 for(int i=0;i<3;i++){
  assert(desktop_next(&h.desktop,&event));
  assert(event.kind==DYN_EVENT_KEY_DOWN&&event.key=='4'&&event.height=='$'&&event.scancode==5);
  assert(event.modifiers&DYN_MOD_SHIFT);assert(event.repeated==(unsigned)(i!=0));
 }
 assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_KEY_UP&&event.height==0x20ac&&event.key=='4');
 assert(!desktop_next(&h.desktop,&event));assert(!h.desktop.pending.text_length);
 mode=1;procedure(NULL,WM_KEYDOWN,'4',message(1));
 assert(desktop_next(&h.desktop,&event)&&event.height==0x1f600&&event.key=='4');
 for(mode=2;mode<=6;mode++){
  procedure(NULL,WM_KEYDOWN,'4',message(1));
  assert(desktop_next(&h.desktop,&event)&&!event.height&&event.key=='4');
 }
 mode=0;keyboard[VK_CONTROL]=keyboard[VK_LCONTROL]=0x80;
 procedure(NULL,WM_KEYDOWN,'4',message(1));
 assert(desktop_next(&h.desktop,&event)&&event.height=='4'&&(event.modifiers&DYN_MOD_CONTROL));
 assert(keyboard[VK_CONTROL]==0x80&&keyboard[VK_LCONTROL]==0x80);
 keyboard[VK_MENU]=keyboard[VK_RMENU]=0x80;
 procedure(NULL,WM_KEYDOWN,'4',message(1));
 assert(desktop_next(&h.desktop,&event)&&event.height==0x20ac&&(event.modifiers&DYN_MOD_ALT));
 memset(keyboard,0,sizeof(keyboard));
 unavailable=1;int before=snapshots;procedure(NULL,WM_KEYDOWN,'4',message(1));
 assert(desktop_next(&h.desktop,&event)&&!event.height&&snapshots==before);
 /* Snapshot queries do not insert text; the existing WM_CHAR path owns it. */
 assert(!h.desktop.pending.text_length);procedure(NULL,WM_CHAR,'x',message(1));
 assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_TEXT&&event.text_length==1&&event.text[0]=='x');
 assert(h.desktop.pending.text_length==1&&h.desktop.pending.text[0]=='x');
 puts("PASS Win32 production KEY.height: modifier/layout snapshots, repeats, surrogate scalar, deadkey/multiscalar rejection, independent WM_CHAR");return 0;
}
'''
def zig_path():
    candidate=shutil.which('zig')
    candidates=([Path(candidate).resolve()] if candidate else [])
    candidates+=sorted((Path.home()/'.local/share/mise/installs/zig').glob('*/zig'))
    for path in candidates:
        if path.is_file() and os.access(path,os.X_OK):
            try:
                subprocess.run([str(path),'version'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
                return str(path)
            except (OSError,subprocess.SubprocessError):pass
    return None
with tempfile.TemporaryDirectory(prefix='dyn-keyboard-win32-') as directory:
    work=Path(directory);source=work/'probe.c';source.write_text(SOURCE)
    zig=zig_path()
    if zig:
        for target in ('x86_64-windows-gnu','aarch64-windows-gnu'):
            subprocess.run([zig,'cc','-target',target,'-std=c11','-Wall','-Wextra','-Werror','-I'+str(NATIVE),'-c',str(source),'-o',str(work/(target+'.o'))],check=True,timeout=180)
        print('PASS strict Windows x64/ARM64 production keyboard compilation',flush=True)
        if shutil.which('wine'):
            output=work/'probe.exe'
            subprocess.run([zig,'cc','-target','x86_64-windows-gnu','-I'+str(NATIVE),str(source),'-luser32','-lgdi32','-lopengl32','-limm32','-o',str(output)],check=True,timeout=180)
            subprocess.run(['wine',str(output)],check=True,timeout=90)
        else:print('SKIP Wine controlled keyboard oracle unavailable')
    else:print('SKIP Windows toolchain unavailable')
print('QUALIFICATION GAP: controlled keyboard APIs do not qualify actual Windows layouts, IME/deadkey state or native desktop execution; no global input generated')
