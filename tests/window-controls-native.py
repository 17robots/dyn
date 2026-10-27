#!/usr/bin/env python3
"""Production native control validation and ordered keyboard layout snapshots."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT/'vendor/window/native'
PROBE = r'''
#include "wayland.c"
#include <assert.h>
#include <stdio.h>
int main(void) {
 Host h = {0};
 assert(!dyn_window_set_title(NULL,NULL,0));
 assert(!dyn_window_set_size(NULL,1,1));
 assert(!dyn_window_set_swap_interval(NULL,0));
 h.toplevel = (void *)1;
 assert(dyn_window_set_title(&h,(const uint8_t *)"x",4097)==-2);
 assert(!dyn_window_set_title(&h,(const uint8_t *)"a\0b",3));
 assert(!dyn_window_set_title(&h,(const uint8_t *)"\xc0\x80",2));
 h.window = (void *)1; h.scale = 2; h.size_constrained = 1;
 assert(!dyn_window_set_size(&h,3,4));
 assert(dyn_window_set_size(&h,4,4)==-1);
 h.xkb = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
 struct xkb_rule_names names = {.layout="us,de",.options="lv3:ralt_switch"};
 h.keymap = xkb_keymap_new_from_names(h.xkb,&names,XKB_KEYMAP_COMPILE_NO_FLAGS);
 assert(h.keymap); h.state = xkb_state_new(h.keymap); assert(h.state);
 desktop_listen(&h.desktop,1);
 xkb_mod_index_t shift = xkb_keymap_mod_get_index(h.keymap,XKB_MOD_NAME_SHIFT);
 xkb_state_update_mask(h.state,1u<<shift,0,0,0,0,0);
 event_keyboard(&h,30,1,0);
 xkb_state_update_mask(h.state,0,0,0,0,0,0);
 event_keyboard(&h,30,0,0);
 dyn_window_event e;
 assert(desktop_next(&h.desktop,&e) && e.key=='a' && e.height=='A');
 assert(desktop_next(&h.desktop,&e) && e.height=='a');
 xkb_state_update_mask(h.state,0,0,0,0,0,1);
 event_keyboard(&h,21,1,0);
 xkb_state_update_mask(h.state,0,0,0,0,0,0);
 assert(desktop_next(&h.desktop,&e) && e.key=='z' && e.height=='z');
 xkb_mod_index_t altgr = xkb_keymap_mod_get_index(h.keymap,"Mod5");
 assert(altgr != XKB_MOD_INVALID);
 xkb_state_update_mask(h.state,1u<<altgr,0,0,0,0,1);
 event_keyboard(&h,16,1,0);
 xkb_state_update_mask(h.state,0,0,0,0,0,0);
 assert(desktop_next(&h.desktop,&e) && e.key=='q' && e.height=='@');
 xkb_state_unref(h.state);xkb_keymap_unref(h.keymap);xkb_context_unref(h.xkb);
 if (getenv("WAYLAND_DISPLAY") && *getenv("WAYLAND_DISPLAY")) {
   Host *live = dyn_window_open("native controls",240,160); assert(live);
   assert(dyn_window_set_title(live,(const uint8_t *)"Unicode \xc3\xa9",10)==1);
   assert(dyn_window_current(live));
   assert(dyn_window_set_swap_interval(live,1)==1);
   int result = dyn_window_set_size(live,260*live->scale,180*live->scale);
   assert(result==1 || result==-1);
   assert(dyn_window_swap(live));
   EGLint w=0, height=0;
   assert(eglQuerySurface(live->egl,live->target,EGL_WIDTH,&w));
   assert(eglQuerySurface(live->egl,live->target,EGL_HEIGHT,&height));
   assert(w==live->frame.width && height==live->frame.height);
   dyn_window_close(live);
   puts("PASS live Wayland/EGL controls");
 }
 puts("PASS native controls and queued layout/shift snapshots");
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-controls-') as directory:
    work=Path(directory)
    subprocess.run(['python3',str(NATIVE/'build.py'),'--output',str(work/'libdyn_window.so')],check=True)
    (work/'probe.c').write_text(PROBE)
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','wayland-client','wayland-egl','wayland-cursor','xkbcommon','egl'],text=True))
    subprocess.run(['cc','-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror','-I'+str(NATIVE),'-I'+str(work),str(work/'probe.c'),str(work/'xdg-shell-protocol.c'),str(work/'text-input-unstable-v3-protocol.c'),*flags,'-o',str(work/'probe')],check=True)
    subprocess.run([str(work/'probe')],check=True,timeout=30)
    if not shutil.which('zig'):
        print('SKIP Windows x64/ARM64 cross-build: zig unavailable')
    if shutil.which('zig'):
        for target in ('x86_64-windows-gnu','aarch64-windows-gnu'):
            subprocess.run(['zig','cc','-target',target,'-std=c11','-Wall','-Wextra','-Werror','-c',str(NATIVE/'win32.c'),'-o',str(work/(target+'.o'))],check=True,timeout=120)
