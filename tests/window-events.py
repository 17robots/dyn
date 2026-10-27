#!/usr/bin/env python3
"""Ordered window events, explicit overflow, opt-in compatibility and worker wake."""
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[1]
SUFFIX = '.exe' if os.name == 'nt' else ''
DYN = str(Path(os.environ.get('DYN', ROOT/('build/dyn-release'+SUFFIX))).resolve())
CC = shlex.split(os.environ.get('CC','cc'))
HAVE_CC = bool(CC) and shutil.which(CC[0]) is not None
SOURCE = r'''use "vendor/window/events" events
fn check(ok: bool) { if !ok { #panic("ordered event queue") } }
fn main() {
  queue := events.Queue{}
  value := events.Event{}
  check(!events.next(&queue, &value))
  for i in 0..events.capacity { events.push(&queue, events.Event{kind:events.Kind.KeyDown,key:#cast(u32,i)}) }
  events.push(&queue, events.Event{kind:events.Kind.Close})
  check(events.next(&queue,&value) && value.key == 0)
  events.push(&queue, events.Event{kind:events.Kind.Close})
  for i in 1..events.capacity { check(events.next(&queue,&value) && value.kind == events.Kind.KeyDown && value.key == #cast(u32,i)) }
  check(events.next(&queue,&value) && value.kind == events.Kind.Overflow && value.dropped == 2)
  check(!events.next(&queue,&value))
  events.push(&queue,events.Event{kind:events.Kind.Wake})
  check(events.next(&queue,&value) && value.kind == events.Kind.Wake)
}
'''
C = r'''#define _POSIX_C_SOURCE 200809L
#include <X11/Xlib.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <time.h>
void dyn_send_key(Display *d, Window w, unsigned long sym, unsigned state, int down) {
 XEvent e={0}; e.xkey.type=down?KeyPress:KeyRelease;e.xkey.display=d;e.xkey.window=w;
 e.xkey.root=DefaultRootWindow(d);e.xkey.state=state;e.xkey.keycode=XKeysymToKeycode(d,sym);e.xkey.same_screen=True;
 XSendEvent(d,w,False,down?KeyPressMask:KeyReleaseMask,&e); XSync(d,False);
}
void dyn_send_close(Display*d,Window w,Atom protocol,Atom atom) {
 XEvent e={0};e.xclient.type=ClientMessage;e.xclient.window=w;e.xclient.message_type=protocol;e.xclient.format=32;e.xclient.data.l[0]=(long)atom;
 XSendEvent(d,w,False,NoEventMask,&e);XSync(d,False);
}
typedef struct Work { pthread_t thread; int (*wake)(void *); void *context; int result; } Work;
static void *run(void*p) { Work*w=p;struct timespec t={0,20000000};nanosleep(&t,NULL);w->result=w->wake(w->context);return NULL; }
void *dyn_wake_thread(int (*wake)(void*),void *context) {
 Work*w=calloc(1,sizeof(*w));if(!w)return NULL;w->wake=wake;w->context=context;
 if(pthread_create(&w->thread,NULL,run,w)){free(w);return NULL;}return w;
}
int dyn_join_wake(void*p){Work*w=p;pthread_join(w->thread,NULL);int result=w->result;free(w);return result;}
'''
X11 = r'''use "vendor/window" window
use "vendor/window/events" events
use "std/time" time
#link("pthread")
#link("c")
extern fn key "dyn_send_key"(display:rawptr,handle:usize,symbol:usize,modifiers:u32,down:i32)
extern fn close_event "dyn_send_close"(display:rawptr,handle:usize,protocol:usize,atom:usize)
extern fn wake_thread "dyn_wake_thread"(callback:fn(rawptr)i32,context:rawptr) rawptr
extern fn join_wake "dyn_join_wake"(worker:rawptr) i32
fn check(ok:bool) { if !ok { #panic("ordered X11 events") } }
fn callback(context:rawptr) i32 {
  if window.wake(#cast(*window.Window,context)).ok { return 1 }
  return 0
}
fn drain(host:*window.Window) {
 event := window.Event{}
 for window.next_event(host,&event) {}
}
fn main() {
 host := window.Window{}
 check(window.open(&host,"ordered events",80,80).ok)
 defer { window.close(&host) }
 _ = window.poll(&host)
 event := window.Event{}
 // Listening is explicitly opt-in; legacy summary clients accumulate nothing.
 key(host.display,host.handle,0x61,0,1)
 check(window.poll(&host).ok && !window.next_event(&host,&event))
 key(host.display,host.handle,0x61,0,0)
 _ = window.poll(&host)
 window.listen_events(&host,true)
 key(host.display,host.handle,0x61,0,1)
 key(host.display,host.handle,0x61,0,0)
 key(host.display,host.handle,0xff51,4,1)
 key(host.display,host.handle,0xff51,4,0)
 check(window.poll(&host).ok)
 check(window.next_event(&host,&event) && event.kind == events.Kind.KeyDown && event.key == 97 && event.repeated == 0 && event.scancode != 0)
 check(window.next_event(&host,&event) && event.kind == events.Kind.Text && event.text_length == 1 && event.text[0] == 97)
 saved := event
 check(window.next_event(&host,&event) && event.kind == events.Kind.KeyUp && event.key == 97)
 check(window.next_event(&host,&event) && event.kind == events.Kind.KeyDown && event.key == events.Left && event.modifiers & events.Control != 0)
 check(window.next_event(&host,&event) && event.kind == events.Kind.KeyUp && event.key == events.Left)
 check(!window.next_event(&host,&event) && saved.text[0] == 97)
 key(host.display,host.handle,0x62,0,1)
 key(host.display,host.handle,0x62,0,1)
 check(window.poll(&host).ok)
 check(window.next_event(&host,&event) && event.kind == events.Kind.KeyDown && event.repeated == 0)
 check(window.next_event(&host,&event) && event.kind == events.Kind.Text && event.text[0] == 98)
 check(window.next_event(&host,&event) && event.kind == events.Kind.KeyDown && event.repeated == 1)
 check(window.next_event(&host,&event) && event.kind == events.Kind.Text)
 check(saved.text[0] == 97)
 key(host.display,host.handle,0x62,0,0)
 _ = window.poll(&host)
 drain(&host)
 for i in 0..200 { _ = i
   key(host.display,host.handle,0xff51,0,1) }
 check(window.poll(&host).ok)
 for i in 0..128 { _ = i
   check(window.next_event(&host,&event) && event.kind == events.Kind.KeyDown && event.key == events.Left) }
 check(window.next_event(&host,&event) && event.kind == events.Kind.Overflow && event.dropped == 72)
 check(!window.next_event(&host,&event))
 window.listen_events(&host,false)
 key(host.display,host.handle,0xff51,0,0)
 _ = window.poll(&host)
 check(!window.next_event(&host,&event))
 window.listen_events(&host,true)
 // Wake must interrupt a GUI wait from a real pthread without touching Xlib.
 worker := wake_thread(callback,&host)
 check(worker != nil)
 now := time.monotonic_now().value
 found := false
 for !found {
   window.wait(&host,1000)
   check(window.poll(&host).ok)
   for window.next_event(&host,&event) { if event.kind == events.Kind.Wake { found = true } }
   check(time.elapsed(now,time.monotonic_now().value).value < 500000000)
 }
 check(join_wake(worker) == 1)
 close_event(host.display,host.handle,host.protocol_atom,host.close_atom)
 check(window.poll(&host).ok && host.close_requested)
 check(window.next_event(&host,&event) && event.kind == events.Kind.Close)
}
'''
WAYLAND_WAKE = r'''use "vendor/window/wayland" window
use "vendor/window/events" events
use "std/time" time
#link("pthread")
#link("c")
extern fn wake_thread "dyn_wake_thread"(callback:fn(rawptr)i32,context:rawptr) rawptr
extern fn join_wake "dyn_join_wake"(worker:rawptr) i32
fn check(ok:bool){if !ok{#panic("Wayland external wake")}}
fn callback(context:rawptr)i32 { if window.wake(#cast(*window.Window,context)).ok{return 1}
 return 0 }
fn main(){
 host:=window.Window{}
 check(window.open(&host,"Wayland external wake",64,64).ok)
 defer{window.close(&host)}
 window.listen_events(&host,true)
 check(window.poll(&host).ok)
 event:=window.Event{}
 for window.next_event(&host,&event){}
 worker:=wake_thread(callback,&host)
 check(worker!=nil)
 started:=time.monotonic_now().value
 found:=false
 for !found {
  window.wait(&host,1000)
  check(window.poll(&host).ok)
  for window.next_event(&host,&event){if event.kind==events.Kind.Wake {found=true}}
  check(time.elapsed(started,time.monotonic_now().value).value<500000000)
 }
 check(join_wake(worker)==1)
}
'''
XIM_MOCK = r'''#include <X11/Xlib.h>
#include <stdlib.h>
int Xutf8LookupString(XIC context,XKeyPressedEvent *event,char *buffer,int capacity,KeySym *key,Status *status) {
 (void)context;(void)event;
 static int calls=0;
 int split=getenv("DYN_TEST_SPLIT_COMMIT")!=NULL;
 int needed=split?(calls++?4:255):(getenv("DYN_TEST_LARGE_COMMIT")?5000:700);
 *key=97;
 if(needed>capacity){*status=XBufferOverflow;return needed;}
 for(int i=0;i<needed;i++)buffer[i]='a';
 if(split&&needed==4){buffer[0]=(char)0xf0;buffer[1]=(char)0x9f;buffer[2]=(char)0x98;buffer[3]=(char)0x80;}
 *status=XLookupBoth;return needed;
}
'''
XIM_SOURCE = r'''use "vendor/window" window
use "vendor/window/events" events
use "std/unicode/utf8" utf8
use "std/process" process
use "std/mem" mem
extern fn key "dyn_send_key"(display:rawptr,handle:usize,symbol:usize,modifiers:u32,down:i32)
fn check(ok:bool){if !ok{#panic("XIM commit bounds")}}
fn main(){
 arena:=mem.Arena{}
 defer{mem.arena_release(&arena)}
 split:=process.environment(&arena,"DYN_TEST_SPLIT_COMMIT").found
 host:=window.Window{}
 check(window.open(&host,"XIM commit bounds",64,64).ok)
 defer{window.close(&host)}
 _=window.poll(&host)
 window.listen_events(&host,true)
 original:=host.desktop.context
 // The interposed lookup never dereferences XIC. Force the production lookup
 // branch even when the test display offers no input method.
 host.desktop.context=#cast(rawptr,1)
 key(host.display,host.handle,0x61,0,1)
 if split {key(host.display,host.handle,0x62,0,1)}
 check(window.poll(&host).ok)
 host.desktop.context=original
 event:=window.Event{}
 check(window.next_event(&host,&event)&&event.kind==events.Kind.KeyDown)
 total:usize=0
 overflow:=false
 for window.next_event(&host,&event){
  if event.kind==events.Kind.Text { total+=#cast(usize,event.text_length)
    check(utf8.valid(events.text(&event))) }
  else if event.kind==events.Kind.Overflow {check(event.dropped==1)
    overflow=true}
  else{check(split&&event.kind==events.Kind.KeyDown)}
 }
 check((total==700&&!overflow)||(total==259&&!overflow&&split)||(total==0&&overflow))
 summary:=window.box_input(&host).text
 check(utf8.valid(summary))
 if split{check(#len(summary)==255)}
}
'''
WAYLAND_MOCK = r'''#include <assert.h>
#include <string.h>
#include <xkbcommon/xkbcommon.h>
#include <xkbcommon/xkbcommon-compose.h>
static int needed=10,resets=0;
static xkb_keysym_t mock_sym(struct xkb_state*s,xkb_keycode_t k){(void)s;(void)k;return XKB_KEY_a;}
static int mock_mod(struct xkb_state*s,const char*n,enum xkb_state_component c){(void)s;(void)n;(void)c;return 0;}
static enum xkb_compose_feed_result mock_feed(struct xkb_compose_state*s,xkb_keysym_t k){(void)s;(void)k;return XKB_COMPOSE_FEED_ACCEPTED;}
static enum xkb_compose_status mock_status(struct xkb_compose_state*s){(void)s;return XKB_COMPOSE_COMPOSED;}
static int mock_utf8(struct xkb_compose_state*s,char*b,size_t size){(void)s;if((size_t)needed<size){memset(b,'a',(size_t)needed);b[needed]=0;}return needed;}
static void mock_reset(struct xkb_compose_state*s){(void)s;resets++;}
#define xkb_state_key_get_one_sym mock_sym
#define xkb_state_mod_name_is_active mock_mod
#define xkb_compose_state_feed mock_feed
#define xkb_compose_state_get_status mock_status
#define xkb_compose_state_get_utf8 mock_utf8
#define xkb_compose_state_reset mock_reset
#include "wayland.c"
int main(void){
 Host h={0};h.state=(struct xkb_state*)1;h.compose=(struct xkb_compose_state*)1;
 desktop_listen(&h.desktop,1);press(&h,30);
 dyn_window_event event;assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_TEXT&&event.text_length==10&&resets==1);
 needed=128;press(&h,30);
 assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_OVERFLOW&&event.dropped==1&&resets==2);
 assert(!desktop_next(&h.desktop,&event));return 0;
}'''
NATIVE_UNIT = r'''#include "desktop_common.h"
#include <assert.h>
#include <stddef.h>
_Static_assert(sizeof(dyn_window_event)==312,"event size");
_Static_assert(_Alignof(dyn_window_event)==4,"event alignment");
_Static_assert(offsetof(dyn_window_event,key)==4,"key offset");
_Static_assert(offsetof(dyn_window_event,x)==28,"pointer offset");
_Static_assert(offsetof(dyn_window_event,scroll_x)==44,"wheel offset");
_Static_assert(offsetof(dyn_window_event,text_length)==52,"length offset");
_Static_assert(offsetof(dyn_window_event,text)==56,"text offset");
int main(void) {
 Desktop d={0}; dyn_window_event e;
 desktop_simple(&d,DYN_EVENT_CLOSE);assert(!desktop_next(&d,&e));
 desktop_listen(&d,1);
 uint8_t bytes[520],copied[520];memset(bytes,'A',sizeof(bytes));
 bytes[255]=0xf0;bytes[256]=0x9f;bytes[257]=0x98;bytes[258]=0x80;
 desktop_text(&d,bytes,sizeof(bytes));
 size_t used=0;int chunks=0;
 while(desktop_next(&d,&e)) {
  assert(e.kind==DYN_EVENT_TEXT && e.text_length<=256);
  if(!chunks)assert(e.text_length==255);
  for(uint32_t at=0;at<e.text_length;) {
   uint8_t lead=e.text[at];uint32_t width=lead<128?1:lead<224?2:lead<240?3:4;
   assert(at+width<=e.text_length);at+=width;
  }
  memcpy(copied+used,e.text,e.text_length);used+=e.text_length;chunks++;
 }
 assert(used==sizeof(bytes)&&chunks==3&&!memcmp(bytes,copied,used));
 assert(d.pending.text_length==255);
 dyn_window_desktop summary;
 desktop_take(&d,&summary,1);
 desktop_text(&d,(const uint8_t*)"a",1);
 uint8_t large[256];memset(large,'b',sizeof(large));
 desktop_text(&d,large,sizeof(large));
 assert(d.pending.text_length==256&&d.pending.text[0]=='a'&&d.pending.text[255]=='b');
 while(desktop_next(&d,&e)){}
 desktop_take(&d,&summary,1);
 for(unsigned i=0;i<128;i++)desktop_simple(&d,DYN_EVENT_KEY_DOWN);
 desktop_simple(&d,DYN_EVENT_TEXT);assert(desktop_next(&d,&e));
 desktop_simple(&d,DYN_EVENT_TEXT);
 for(unsigned i=1;i<128;i++)assert(desktop_next(&d,&e)&&e.kind==DYN_EVENT_KEY_DOWN);
 assert(desktop_next(&d,&e)&&e.kind==DYN_EVENT_OVERFLOW&&e.dropped==2);
 assert(!desktop_next(&d,&e));
 desktop_simple(&d,DYN_EVENT_WAKE);desktop_listen(&d,0);assert(!desktop_next(&d,&e));
 return 0;
}'''
WIN32 = r'''#include "win32.c"
#include <stdio.h>
static int fail(const char *s) { fprintf(stderr,"FAIL %s\n",s); return 1; }
static DWORD WINAPI waking(void *p) { Sleep(30); return dyn_window_wake(p)?0:1; }
int main(void) {
 Host *h=dyn_window_open("ordered event oracle",64,64);
 if(!h) return fail("open");
 dyn_window_listen_events(h,1);
 dyn_window_frame frame; dyn_window_event event;
 dyn_window_poll(h,&frame); while(dyn_window_next_event(h,&event)){}
 SendMessageW(h->window,WM_KEYDOWN,'A',1 | (30<<16));
 SendMessageW(h->window,WM_CHAR,'a',1);
 SendMessageW(h->window,WM_KEYUP,'A',1 | (30<<16) | ((LPARAM)1<<31));
 dyn_window_poll(h,&frame);
 int seen=0;
 while(dyn_window_next_event(h,&event)) {
  if(event.kind==DYN_EVENT_KEY_DOWN) { if(seen!=0||event.key!='a'||event.scancode!=30||event.repeated) return fail("key down"); seen=1; }
  else if(event.kind==DYN_EVENT_TEXT) { if(seen!=1||event.text_length!=1||event.text[0]!='a') return fail("text"); seen=2; }
  else if(event.kind==DYN_EVENT_KEY_UP) { if(seen!=2||event.key!='a') return fail("key up"); seen=3; }
 }
 if(seen!=3) return fail("ordered stream");
 PostMessageW(h->window,WM_KEYDOWN,VK_LEFT,1 | (75<<16) | ((LPARAM)1<<24) | ((LPARAM)1<<30));
 dyn_window_poll(h,&frame);
 if(!dyn_window_next_event(h,&event)||event.kind!=DYN_EVENT_KEY_DOWN||event.key!=DYN_LEFT_KEY||event.scancode!=331||event.repeated!=1) return fail("repeat/special/extended");
 for(int i=0;i<200;i++) PostMessageW(h->window,WM_CHAR,'x',1);
 dyn_window_poll(h,&frame);
 ULONGLONG before=GetTickCount64();dyn_window_wait(h,250);
 if(GetTickCount64()-before>100) return fail("queued event wait");
 int count=0;uint32_t dropped=0;
 while(dyn_window_next_event(h,&event)) {if(event.kind==DYN_EVENT_TEXT)count++;if(event.kind==DYN_EVENT_OVERFLOW)dropped=event.dropped;}
 if(count!=128||dropped!=72) return fail("bounded overflow");

 dyn_window_desktop summary;
 dyn_window_desktop_take(h,&summary);
 SendMessageW(h->window,WM_KEYDOWN,'A',3 | (30<<16));
 int key_count=0;
 while(dyn_window_next_event(h,&event)) {
  if(event.kind!=DYN_EVENT_KEY_DOWN||event.key!='a'||event.repeated!=(uint32_t)(key_count!=0)) return fail("coalesced key repeats");
  key_count++;
 }
 if(key_count!=3) return fail("coalesced key count");
 SendMessageW(h->window,WM_CHAR,'x',3);
 int text_count=0;
 while(dyn_window_next_event(h,&event)) {
  if(event.kind!=DYN_EVENT_TEXT||event.text_length!=1||event.text[0]!='x') return fail("coalesced text repeats");
  text_count++;
 }
 dyn_window_desktop_take(h,&summary);
 if(text_count!=3||summary.text_length!=3||memcmp(summary.text,"xxx",3)) return fail("coalesced text summary");
 SendMessageW(h->window,WM_CHAR,0xd83d,3);
 SendMessageW(h->window,WM_CHAR,0xde00,3);
 text_count=0;
 while(dyn_window_next_event(h,&event)) {
  const uint8_t expected[4]={0xf0,0x9f,0x98,0x80};
  if(event.kind!=DYN_EVENT_TEXT||event.text_length!=4||memcmp(event.text,expected,4)) return fail("surrogate repeats");
  text_count++;
 }
 dyn_window_desktop_take(h,&summary);
 if(text_count!=3||summary.text_length!=12) return fail("surrogate repeat count");
 SendMessageW(h->window,WM_CHAR,'x',65535);
 count=0;dropped=0;
 while(dyn_window_next_event(h,&event)) {if(event.kind==DYN_EVENT_TEXT)count++;if(event.kind==DYN_EVENT_OVERFLOW)dropped=event.dropped;}
 dyn_window_desktop_take(h,&summary);
 if(count!=128||dropped!=65407||summary.text_length!=256) return fail("max coalesced text overflow");
 SendMessageW(h->window,WM_KEYDOWN,'A',65535 | (30<<16));
 count=0;dropped=0;
 while(dyn_window_next_event(h,&event)) {if(event.kind==DYN_EVENT_KEY_DOWN)count++;if(event.kind==DYN_EVENT_OVERFLOW)dropped=event.dropped;}
 if(count!=128||dropped!=65407) return fail("max coalesced key overflow");
 HANDLE thread=CreateThread(NULL,0,waking,h,0,NULL);
 if(!thread) return fail("thread");
 int woke=0;before=GetTickCount64();
 while(!woke&&GetTickCount64()-before<2000) {dyn_window_wait(h,500);dyn_window_poll(h,&frame);while(dyn_window_next_event(h,&event))if(event.kind==DYN_EVENT_WAKE)woke=1;}
 WaitForSingleObject(thread,2000);CloseHandle(thread);
 if(!woke) return fail("external wake");
 PostMessageW(h->window,WM_CLOSE,0,0);dyn_window_poll(h,&frame);
 int closed=0;while(dyn_window_next_event(h,&event))if(event.kind==DYN_EVENT_CLOSE)closed=1;
 dyn_window_close(h);if(!closed)return fail("close");
 puts("PASS Win32 ordered key/text/release, repeat/scancode, queue overflow, coalesced key/text/surrogate repeats, pending wait, worker wake and close");return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-window-events-') as directory:
    work = Path(directory)
    (work/'main.dyn').write_text(SOURCE)
    for mode in ('--debug','--release'):
        output=work/('queue'+SUFFIX)
        subprocess.run([DYN,'build',str(work),mode,'--quiet','--output',str(output)],check=True,timeout=120)
        subprocess.run([str(output)],check=True,timeout=30)
    for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows','wasm32-wasi'):
        subprocess.run([DYN,'build',str(work),'--release','--target',target,'--quiet','--output',str(work/target)],check=True,timeout=120)
    if HAVE_CC:
        (work/'native-unit.c').write_text(NATIVE_UNIT)
        subprocess.run([*CC,'-std=c11','-Wall','-Wextra','-Werror','-I'+str(ROOT/'vendor/window/native'),str(work/'native-unit.c'),'-o',str(work/('native-unit'+SUFFIX))],check=True)
        subprocess.run([str(work/('native-unit'+SUFFIX))],check=True,timeout=20)
    if sys.platform.startswith('linux') and HAVE_CC and shutil.which('wayland-scanner') and shutil.which('pkg-config'):
        available=subprocess.run(['pkg-config','--exists','wayland-client','wayland-egl','wayland-cursor','xkbcommon','egl','wayland-protocols']).returncode==0
        if available:
            import shlex
            protocol_root=subprocess.check_output(['pkg-config','--variable=pkgdatadir','wayland-protocols'],text=True).strip()
            xml=str(Path(protocol_root)/'stable/xdg-shell/xdg-shell.xml')
            subprocess.run(['wayland-scanner','client-header',xml,str(work/'xdg-shell-client-protocol.h')],check=True)
            subprocess.run(['wayland-scanner','private-code',xml,str(work/'xdg-shell-protocol.c')],check=True)
            text_xml=str(Path(protocol_root)/'unstable/text-input/text-input-unstable-v3.xml')
            subprocess.run(['wayland-scanner','client-header',text_xml,str(work/'text-input-unstable-v3-client-protocol.h')],check=True)
            subprocess.run(['wayland-scanner','private-code',text_xml,str(work/'text-input-unstable-v3-protocol.c')],check=True)
            (work/'wayland-probe.c').write_text(WAYLAND_MOCK)
            flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','wayland-client','wayland-egl','wayland-cursor','xkbcommon','egl'],text=True))
            output=work/'wayland-probe'
            subprocess.run([*CC,'-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror','-I'+str(ROOT/'vendor/window/native'),'-I'+str(work),str(work/'wayland-probe.c'),str(work/'xdg-shell-protocol.c'),str(work/'text-input-unstable-v3-protocol.c'),*flags,'-o',str(output)],check=True,timeout=120)
            subprocess.run([str(output)],check=True,timeout=20)
            if os.environ.get('WAYLAND_DISPLAY'):
                bridge=work/'libdyn_window.so'
                subprocess.run([sys.executable,str(ROOT/'vendor/window/native/build.py'),'--output',str(bridge)],check=True,timeout=120)
                wake_source='#define _POSIX_C_SOURCE 200809L\n#include <pthread.h>\n#include <stdlib.h>\n#include <time.h>\n'+C[C.index('typedef struct Work'):]
                (work/'wake.c').write_text(wake_source)
                subprocess.run([*CC,'-std=c11','-Wall','-Wextra','-Werror','-c',str(work/'wake.c'),'-o',str(work/'wake.o'),'-pthread'],check=True)
                (work/'main.dyn').write_text(WAYLAND_WAKE)
                output=work/'wayland-wake'
                subprocess.run([DYN,'build',str(work),'--release','--quiet','--link',str(bridge),'--link',str(work/'wake.o'),'--output',str(output)],check=True,timeout=120)
                subprocess.run([str(output)],check=True,timeout=20)
    if sys.platform.startswith('linux') and shutil.which('zig') and HAVE_CC:
        (work/'win32-probe.c').write_text(WIN32)
        for target in ('x86_64-windows-gnu','aarch64-windows-gnu'):
            subprocess.run(['zig','cc','-target',target,'-std=c11','-Wall','-Wextra','-Werror','-I'+str(ROOT/'vendor/window/native'),'-c',str(work/'native-unit.c'),'-o',str(work/(target+'.o'))],check=True,timeout=120)
        if shutil.which('wine') and os.environ.get('DISPLAY'):
            output=work/'win32.exe'
            subprocess.run(['zig','cc','-target','x86_64-windows-gnu','-I'+str(ROOT/'vendor/window/native'),str(work/'win32-probe.c'),'-luser32','-lgdi32','-lopengl32','-limm32','-o',str(output)],check=True,timeout=180)
            result=subprocess.run(['wine',str(output)],capture_output=True,text=True,timeout=60)
            if result.returncode: print(result.stderr, file=sys.stderr)
            result.check_returncode()
            print(result.stdout.strip())
    if sys.platform == 'win32' and HAVE_CC:
        (work/'win32-probe.c').write_text(WIN32)
        output=work/'win32-native.exe'
        if os.environ.get('DYN_OPENGL_DLL'):
            driver=Path(os.environ['DYN_OPENGL_DLL']).resolve()
            shutil.copy2(driver,work/'opengl32.dll')
            shutil.copy2(driver.parent/'libgallium_wgl.dll',work/'libgallium_wgl.dll')
        subprocess.run([*CC,'-std=c11','-Wall','-Wextra','-Werror','-I'+str(ROOT/'vendor/window/native'),str(work/'win32-probe.c'),'-luser32','-lgdi32','-lopengl32','-limm32','-o',str(output)],check=True,timeout=180)
        subprocess.run([str(output)],env={**os.environ,'GALLIUM_DRIVER':'llvmpipe'},check=True,timeout=60)
    if sys.platform == 'darwin':
        print('SKIP Cocoa ordered runtime injection: C ABI queue tested; native event/wake qualification remains separate')
    if sys.platform.startswith('linux') and os.environ.get('DISPLAY') and HAVE_CC:
        (work/'probe.c').write_text(C)
        subprocess.run([*CC,'-std=c11','-Wall','-Wextra','-Werror','-c',str(work/'probe.c'),'-o',str(work/'probe.o'),'-pthread'],check=True)
        (work/'main.dyn').write_text(X11)
        for mode in ('--debug','--release'):
            output=work/'x11'
            subprocess.run([DYN,'build',str(work),mode,'--quiet','--link',str(work/'probe.o'),'--output',str(output)],check=True,timeout=120)
            subprocess.run([str(output)],check=True,timeout=20)
        (work/'lookup.c').write_text(XIM_MOCK)
        shim=work/'lookup.so'
        subprocess.run([*CC,'-shared','-fPIC','-Wall','-Wextra','-Werror',str(work/'lookup.c'),'-o',str(shim)],check=True)
        (work/'main.dyn').write_text(XIM_SOURCE)
        output=work/'xim'
        subprocess.run([DYN,'build',str(work),'--debug','--quiet','--link',str(work/'probe.o'),'--output',str(output)],check=True,timeout=120)
        env={**os.environ,'LD_PRELOAD':str(shim)}
        subprocess.run([str(output)],env=env,check=True,timeout=20)
        subprocess.run([str(output)],env={**env,'DYN_TEST_LARGE_COMMIT':'1'},check=True,timeout=20)
        subprocess.run([str(output)],env={**env,'DYN_TEST_SPLIT_COMMIT':'1'},check=True,timeout=20)
    else:
        print('SKIP real X11 event/wake oracle: Linux X display and C compiler required')
print('PASS ordered window events: opt-in compatibility, owned text, key/text order, repeat, bounded overflow, worker wake and close')
