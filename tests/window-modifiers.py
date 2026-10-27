#!/usr/bin/env python3
"""Real X11 keyboard events preserve modifiers while clearing per-frame keys."""
import os
import shutil
import sys
from pathlib import Path
import subprocess,tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
if not sys.platform.startswith('linux') or not os.environ.get('DISPLAY') or not shutil.which('cc'):
 print('SKIP X11 modifier oracle: X display and C compiler required')
 raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-x11-word-') as directory:
 p=Path(directory)
 (p/'send.c').write_text('''#include <X11/Xlib.h>
int dyn_test_send_key(Display *d, Window w, unsigned long sym, unsigned int state, int pressed) {
 XEvent e = {0}; e.xkey.type=pressed?KeyPress:KeyRelease; e.xkey.display=d; e.xkey.window=w;
 e.xkey.root=DefaultRootWindow(d); e.xkey.state=state; e.xkey.keycode=XKeysymToKeycode(d,sym); e.xkey.same_screen=True;
 int r=XSendEvent(d,w,False,pressed?KeyPressMask:KeyReleaseMask,&e); XSync(d,False); return r;
}''')
 subprocess.run(['cc','-fno-stack-protector','-c',str(p/'send.c'),'-o',str(p/'send.o')],check=True)
 (p/'main.dyn').write_text('''use "vendor/window" window
extern fn send "dyn_test_send_key"(display: rawptr, window: usize, symbol: usize, state: u32, pressed: i32) i32
fn check(ok: bool) { if !ok { #panic("X11 word modifier contract") } }
fn key(host: *window.Window, symbol: usize, state: u32, pressed: i32) {
 check(send(host.display, host.handle, symbol, state, pressed) != 0)
 _ = window.poll(host)
}
fn main() {
 host := window.Window{}
 check(window.open(&host, "modifier oracle", 64, 64).ok)
 defer { window.close(&host) }
 _ = window.poll(&host)
 key(&host, 0xff51, 4, 1)
 check(window.box_input(&host).left && window.box_input(&host).control)
 _ = window.poll(&host)
 check(!window.box_input(&host).left && window.box_input(&host).control)
 key(&host, 0xffe3, 4, 0)
 check(!window.box_input(&host).control)
 key(&host, 0xffe1, 0, 1)
 check(window.box_input(&host).shift)
 key(&host, 0xffe1, 1, 0)
 check(!window.box_input(&host).shift)
}''')
 subprocess.run([DYN,'build',str(p),'--debug','--quiet','--link',str(p/'send.o'),'--output',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=30)
 print('PASS X11 synthetic Ctrl+Left, idle persistence, Ctrl release and Shift press/release')
