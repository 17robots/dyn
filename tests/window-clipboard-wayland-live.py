#!/usr/bin/env python3
"""Opt-in clipboard qualification inside an isolated nested niri compositor.

This never connects test clients to the desktop compositor or its clipboard.
Run without arguments for the production C 1.2MB clipboard roundtrip. Use
--run COMMAND ARG... to run an application with private input: one Shift pair
per newly focused window. The runner sets DNA_TEST_WAYLAND_INPUT=1 and cleans
up both its input monitor and compositor when the command exits.
"""
import os
import json
import threading
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'vendor/window/native'
XML='''<protocol name="virtual_keyboard_unstable_v1">
<interface name="zwp_virtual_keyboard_v1" version="1">
<request name="keymap"><arg name="format" type="uint"/><arg name="fd" type="fd"/><arg name="size" type="uint"/></request>
<request name="key"><arg name="time" type="uint"/><arg name="key" type="uint"/><arg name="state" type="uint"/></request>
<request name="modifiers"><arg name="depressed" type="uint"/><arg name="latched" type="uint"/><arg name="locked" type="uint"/><arg name="group" type="uint"/></request>
<request name="destroy" type="destructor"/>
</interface>
<interface name="zwp_virtual_keyboard_manager_v1" version="1">
<request name="create_virtual_keyboard"><arg name="seat" type="object" interface="wl_seat"/><arg name="id" type="new_id" interface="zwp_virtual_keyboard_v1"/></request>
</interface></protocol>'''
PROBE=r'''
#include "wayland.c"
#include "virtual-keyboard-client-protocol.h"
#include <assert.h>
#include <stdio.h>
static struct zwp_virtual_keyboard_manager_v1 *manager;
static void virtual_global(void*p,struct wl_registry*r,uint32_t name,const char*interface,uint32_t version){
 (void)p;(void)version;
 if(!strcmp(interface,"zwp_virtual_keyboard_manager_v1"))manager=wl_registry_bind(r,name,&zwp_virtual_keyboard_manager_v1_interface,1);
}
static void remove_global(void*p,struct wl_registry*r,uint32_t name){(void)p;(void)r;(void)name;}
static const struct wl_registry_listener listener={virtual_global,remove_global};
static void pump(Host*a,Host*b,int milliseconds){
 int64_t end=now_ms()+milliseconds;dyn_window_frame frame;
 do {assert(dyn_window_poll(a,&frame));if(b)assert(dyn_window_poll(b,&frame));usleep(1000);}while(now_ms()<end);
}
int main(void){
 Host *owner=dyn_window_open("isolated clipboard owner",320,240);assert(owner);
 assert(dyn_window_swap(owner));pump(owner,NULL,300);
 struct wl_registry *registry=wl_display_get_registry(owner->display);
 wl_registry_add_listener(registry,&listener,NULL);assert(wl_display_roundtrip(owner->display)>=0);assert(manager);
 struct zwp_virtual_keyboard_v1 *keyboard=zwp_virtual_keyboard_manager_v1_create_virtual_keyboard(manager,owner->seat);
 struct xkb_context *context=xkb_context_new(XKB_CONTEXT_NO_FLAGS);assert(context);
 struct xkb_rule_names names={.layout="us"};struct xkb_keymap *keymap=xkb_keymap_new_from_names(context,&names,XKB_KEYMAP_COMPILE_NO_FLAGS);assert(keymap);
 char *text=xkb_keymap_get_as_string(keymap,XKB_KEYMAP_FORMAT_TEXT_V1);assert(text);
 int fd=memfd_create("dyn-isolated-keymap",MFD_CLOEXEC);assert(fd>=0);size_t size=strlen(text)+1;assert(write(fd,text,size)==(ssize_t)size);
 zwp_virtual_keyboard_v1_keymap(keyboard,WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1,fd,(uint32_t)size);close(fd);free(text);xkb_keymap_unref(keymap);xkb_context_unref(context);
 zwp_virtual_keyboard_v1_key(keyboard,1,30,WL_KEYBOARD_KEY_STATE_PRESSED);zwp_virtual_keyboard_v1_key(keyboard,2,30,WL_KEYBOARD_KEY_STATE_RELEASED);
 pump(owner,NULL,300);assert(owner->serial);
 uint32_t length=1200000;uint8_t *bytes=malloc(length);assert(bytes);memset(bytes,'q',length);
 assert(dyn_window_try_set_clipboard(owner,bytes,length)==1);pump(owner,NULL,100);
 Host *receiver=dyn_window_open("isolated clipboard receiver",320,240);assert(receiver);assert(dyn_window_swap(receiver));pump(owner,receiver,400);
 assert(receiver->offer&&receiver->offer_text);
 dyn_window_request_paste_snapshot(receiver);assert(dyn_window_paste_pending(receiver));
 int64_t end=now_ms()+10000;
 while(dyn_window_paste_pending(receiver)&&now_ms()<end)pump(owner,receiver,1);
 const uint8_t *received;assert(dyn_window_paste_status(receiver)==1);
 assert(dyn_window_clipboard_get(receiver,&received)==length&&!memcmp(bytes,received,length));
 assert(!receiver->desktop.event_count&&!receiver->desktop.event_dropped);
 /* Publish an empty selection using the receiver's own real input serial. */
 zwp_virtual_keyboard_v1_key(keyboard,3,48,WL_KEYBOARD_KEY_STATE_PRESSED);zwp_virtual_keyboard_v1_key(keyboard,4,48,WL_KEYBOARD_KEY_STATE_RELEASED);pump(owner,receiver,100);assert(receiver->serial);
 assert(dyn_window_try_set_clipboard(receiver,NULL,0)==1);pump(owner,receiver,100);
 dyn_window_request_paste_snapshot(receiver);assert(dyn_window_paste_status(receiver)==1&&dyn_window_clipboard_get(receiver,&received)==0);
 free(bytes);zwp_virtual_keyboard_v1_destroy(keyboard);wl_proxy_destroy((struct wl_proxy*)manager);wl_registry_destroy(registry);
 dyn_window_close(receiver);dyn_window_close(owner);
 puts("PASS isolated live niri: real input serial, 1.2MB clipboard source/pipe/offer snapshot roundtrip and empty publication");
}
'''
INJECT=r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <wayland-client.h>
#include <xkbcommon/xkbcommon.h>
#include "virtual-keyboard-client-protocol.h"
static struct wl_seat *seat;
static struct zwp_virtual_keyboard_manager_v1 *manager;
static void global(void*p,struct wl_registry*r,uint32_t name,const char*interface,uint32_t version){
 (void)p;(void)version;
 if(!strcmp(interface,"wl_seat"))seat=wl_registry_bind(r,name,&wl_seat_interface,1);
 if(!strcmp(interface,"zwp_virtual_keyboard_manager_v1"))manager=wl_registry_bind(r,name,&zwp_virtual_keyboard_manager_v1_interface,1);
}
static void removed(void*p,struct wl_registry*r,uint32_t name){(void)p;(void)r;(void)name;}
static const struct wl_registry_listener listener={global,removed};
int main(void){
 struct wl_display *display=wl_display_connect(NULL);assert(display);
 struct wl_registry *registry=wl_display_get_registry(display);wl_registry_add_listener(registry,&listener,NULL);
 assert(wl_display_roundtrip(display)>=0&&seat&&manager);
 struct zwp_virtual_keyboard_v1 *keyboard=zwp_virtual_keyboard_manager_v1_create_virtual_keyboard(manager,seat);
 struct xkb_context *context=xkb_context_new(XKB_CONTEXT_NO_FLAGS);assert(context);
 struct xkb_rule_names names={.layout="us"};struct xkb_keymap *keymap=xkb_keymap_new_from_names(context,&names,XKB_KEYMAP_COMPILE_NO_FLAGS);assert(keymap);
 char *text=xkb_keymap_get_as_string(keymap,XKB_KEYMAP_FORMAT_TEXT_V1);assert(text);
 int fd=memfd_create("dyn-isolated-injector-keymap",MFD_CLOEXEC);assert(fd>=0);size_t size=strlen(text)+1;
 assert(write(fd,text,size)==(ssize_t)size);zwp_virtual_keyboard_v1_keymap(keyboard,WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1,fd,(uint32_t)size);
 close(fd);free(text);xkb_keymap_unref(keymap);xkb_context_unref(context);
 /* The runner invokes this once per newly focused private window. */
 for(uint32_t tick=1;tick<2;tick++){
   zwp_virtual_keyboard_v1_key(keyboard,tick*50,42,WL_KEYBOARD_KEY_STATE_PRESSED);
   zwp_virtual_keyboard_v1_key(keyboard,tick*50+1,42,WL_KEYBOARD_KEY_STATE_RELEASED);
   if(wl_display_flush(display)<0)break;
   usleep(50000);
 }
 wl_display_disconnect(display);return 0;
}
'''
command=None
if len(sys.argv)>1:
    if sys.argv[1]!='--run' or len(sys.argv)<3:
        raise SystemExit('usage: window-clipboard-wayland-live.py [--run COMMAND ARG...]')
    command=sys.argv[2:]
if not sys.platform.startswith('linux') or not shutil.which('niri'):
    print('SKIP isolated live clipboard: niri unavailable');sys.exit(0)
parent_display=os.environ.get('WAYLAND_DISPLAY')
parent_runtime=os.environ.get('XDG_RUNTIME_DIR')
if not parent_display or not parent_runtime:
    print('SKIP isolated live clipboard: parent Wayland display unavailable');sys.exit(0)
with tempfile.TemporaryDirectory(prefix='dyn-wayland-live-') as directory:
    work=Path(directory);runtime=work/'runtime';runtime.mkdir(mode=0o700)
    (work/'config.kdl').write_text('')
    subprocess.run([sys.executable,str(NATIVE/'build.py'),'--output',str(work/'libdyn_window.so')],check=True,timeout=120)
    (work/'virtual-keyboard.xml').write_text(XML)
    for mode,output in [('client-header','virtual-keyboard-client-protocol.h'),('private-code','virtual-keyboard-protocol.c')]:
        subprocess.run(['wayland-scanner',mode,str(work/'virtual-keyboard.xml'),str(work/output)],check=True)
    (work/'probe.c').write_text(PROBE)
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','wayland-client','wayland-egl','wayland-cursor','xkbcommon','egl'],text=True))
    subprocess.run(['cc','-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror','-I'+str(NATIVE),'-I'+str(work),str(work/'probe.c'),str(work/'xdg-shell-protocol.c'),str(work/'text-input-unstable-v3-protocol.c'),str(work/'virtual-keyboard-protocol.c'),*flags,'-o',str(work/'probe')],check=True,timeout=120)
    if command:
        (work/'inject.c').write_text(INJECT)
        subprocess.run(['cc','-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror','-I'+str(work),str(work/'inject.c'),str(work/'virtual-keyboard-protocol.c'),*flags,'-o',str(work/'inject')],check=True,timeout=120)
    env=dict(os.environ);env['XDG_RUNTIME_DIR']=str(runtime);env['WAYLAND_DISPLAY']=str(Path(parent_runtime)/parent_display) if not parent_display.startswith('/') else parent_display
    env.pop('WAYLAND_SOCKET',None);env.pop('NIRI_SOCKET',None)
    log=(work/'compositor.log').open('w+')
    compositor=subprocess.Popen(['niri','-c',str(work/'config.kdl'),'--','sh','-c','printf "%s\\n" "$WAYLAND_DISPLAY" > "$XDG_RUNTIME_DIR/test-display"'],env=env,stdout=log,stderr=subprocess.STDOUT)
    try:
        deadline=time.monotonic()+10
        marker=runtime/'test-display'
        while not marker.exists() and compositor.poll() is None and time.monotonic()<deadline:time.sleep(.02)
        if not marker.exists():
            log.seek(0);raise RuntimeError('isolated compositor failed: '+log.read())
        child_env=dict(env);child_env['WAYLAND_DISPLAY']=marker.read_text().strip();child_env.pop('DISPLAY',None)
        if command:
            child_env['DNA_TEST_WAYLAND_INPUT']='1'
            sockets=list(runtime.glob('niri.*.sock'))
            assert len(sockets)==1
            child_env['NIRI_SOCKET']=str(sockets[0])
            stopped=threading.Event()
            failures=[]
            def supply_input():
                seen=set()
                try:
                    while not stopped.wait(.05):
                        result=subprocess.run(['niri','msg','-j','focused-window'],env=child_env,capture_output=True,text=True,check=True,timeout=3)
                        focused=json.loads(result.stdout)
                        if focused and focused['id'] not in seen:
                            subprocess.run([str(work/'inject')],env=child_env,check=True,timeout=3)
                            seen.add(focused['id'])
                except Exception as error:
                    failures.append(error)
            injector=threading.Thread(target=supply_input,daemon=True)
            injector.start()
            try:
                subprocess.run(command,env=child_env,check=True,timeout=120)
                if failures:raise failures[0]
            finally:
                stopped.set();injector.join(timeout=5)
        else:
            subprocess.run([str(work/'probe')],env=child_env,check=True,timeout=25)
    finally:
        compositor.terminate()
        try:compositor.wait(timeout=5)
        except subprocess.TimeoutExpired:compositor.kill();compositor.wait()
        log.close()
