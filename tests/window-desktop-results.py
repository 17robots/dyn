#!/usr/bin/env python3
"""vendor/window desktop input on every available backend: clipboard round trip, cursors, scale, wait and box_input."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "vendor/window" window
use "std/bytes" bytes

fn check(ok: bool, message: []const u8) {
  if !ok {
    #panic(message)
  }
}

fn main() {
  host := window.Window{}
  check(window.open(&host, "Dyn desktop input test", 96, 64).ok, "open")
  defer {
    window.close(&host)
  }
  _ = window.poll(&host)
  window.listen_events(&host, true)
  check(window.wake(&host).ok, "wake accepted")
  window.wait(&host, 100)
  check(window.poll(&host).ok, "poll wake")
  event := window.Event{}
  woke := false
  for window.next_event(&host, &event) {
    if event.kind == window.EventKind.Wake { woke = true }
  }
  check(woke, "native event ABI wake round trip")
  window.listen_events(&host, false)
  check(!window.next_event(&host, &event), "disable clears stream")
  check(window.scale(&host) > 0.0, "scale")
  window.set_cursor(&host, window.Cursor.Text)
  window.set_cursor(&host, window.Cursor.Arrow)
  quiet := window.box_input(&host)
  check(#len(quiet.text) == 0 && !quiet.paste, "no input yet")
  window.listen_events(&host, true)
  check(window.try_set_clipboard(&host, "clip ✓ text").ok, "clipboard publication")
  window.request_paste(&host)
  got := false
  for i in 0..300 {
    _ = window.poll(&host)
    input := window.box_input(&host)
    if input.paste {
      check(bytes.equal(input.clipboard, "clip ✓ text"), "clipboard text")
      got = true
      break
    }
    window.wait(&host, 10)
  }
  check(got, "paste arrived")
  clip_event := false
  for window.next_event(&host, &event) {
    if event.kind == window.EventKind.Clipboard {
      check(event.x == 0 && event.button == 1 && bytes.equal(event.text[..#cast(usize, event.text_length)], "clip ✓ text"), "owned clipboard payload")
      clip_event = true
    }
  }
  check(clip_event, "ordered paste arrived")
  window.set_clipboard(&host, "first")
  window.request_paste(&host)
  window.set_clipboard(&host, "second")
  window.request_paste(&host)
  _ = window.poll(&host)
  replies: usize = 0
  for window.next_event(&host, &event) {
    if event.kind == window.EventKind.Clipboard {
      if replies == 0 { check(bytes.equal(event.text[..#cast(usize, event.text_length)], "first"), "first reply survives latest snapshot") }
      else { check(bytes.equal(event.text[..#cast(usize, event.text_length)], "second"), "second reply order") }
      replies += 1
    }
  }
  check(replies == 2 && bytes.equal(window.clipboard(&host), "second"), "two owned replies and borrowed latest")
  window.listen_events(&host, false)
  _ = window.poll(&host)
  check(!window.box_input(&host).paste, "paste is one frame")
  // No input method composes during the test: the composition stays empty.
  window.set_text_input(&host, true, 10, 12, 1, 16)
  _ = window.poll(&host)
  check(#len(window.box_input(&host).composition) == 0 && window.box_input(&host).composition_cursor == -1, "no composition")
  window.set_text_input(&host, false, 0, 0, 0, 0)
  window.wait(&host, 20)
}
'''
results = []
with tempfile.TemporaryDirectory(prefix='dyn-window-desktop-') as directory:
    work = Path(directory)
    if sys.platform.startswith('linux') and os.environ.get('DISPLAY'):
        project = work / 'x11'
        project.mkdir()
        (project / 'main.dyn').write_text(SOURCE, encoding='utf-8')
        subprocess.run([DYN, 'build', str(project), '--quiet', '--no-cache', '--output', str(project / 'program')], check=True, timeout=300)
        subprocess.run([str(project / 'program')], check=True, timeout=60)
        results.append('X11')
    if sys.platform.startswith('linux') and os.environ.get('WAYLAND_DISPLAY') and shutil.which('wayland-scanner'):
        project = work / 'wayland'
        project.mkdir()
        # A Wayland selection requires a real input serial. Supply input only
        # inside the private compositor, never through the user's desktop.
        source = SOURCE.replace('use "vendor/window" window', 'use "vendor/window/wayland" window')
        source = source.replace('  _ = window.poll(&host)', '  check(window.swap(&host).ok, "map window")\n  _ = window.poll(&host)', 1)
        source = source.replace(
            '  check(window.try_set_clipboard(&host, "clip ✓ text").ok, "clipboard publication")',
            '  for i in 0..300 {\n    if window.try_set_clipboard(&host, "clip ✓ text").ok { break }\n    _ = window.poll(&host)\n    window.wait(&host, 10)\n  }\n  check(window.try_set_clipboard(&host, "clip ✓ text").ok, "clipboard publication after input")')
        (project / 'main.dyn').write_text(source, encoding='utf-8')
        bridge = project / 'libdyn_window.so'
        subprocess.run([sys.executable, str(ROOT / 'vendor/window/native/build.py'), '--output', str(bridge)], check=True, timeout=120)
        subprocess.run([DYN, 'build', str(project), '--quiet', '--no-cache', '--link', str(bridge), '--output', str(project / 'program')], check=True, timeout=300)
        if shutil.which('niri') and os.environ.get('XDG_RUNTIME_DIR'):
            subprocess.run([sys.executable, str(ROOT / 'tests/window-clipboard-wayland-live.py'),
                            '--run', str(project / 'program')], check=True, timeout=180)
            results.append('Wayland (isolated input)')
        else:
            print('SKIP live Wayland clipboard: isolated niri input requires niri and XDG_RUNTIME_DIR; cross-build passed')
    if sys.platform.startswith('linux') and shutil.which('zig') and shutil.which('wine') and os.environ.get('DISPLAY'):
        project = work / 'wine'
        project.mkdir()
        (project / 'main.dyn').write_text(SOURCE, encoding='utf-8')
        bridge = project / 'dyn_window.dll'
        library = project / 'libdyn_window.dll.a'
        subprocess.run(['zig', 'cc', '-target', 'x86_64-windows-gnu', '-shared', str(ROOT / 'vendor/window/native/win32.c'), '-luser32', '-lgdi32', '-lopengl32','-limm32',
                        '-Wl,--out-implib,' + str(library), '-o', str(bridge)], check=True, timeout=180)
        subprocess.run([DYN, 'build', str(project), '--target', 'x86_64-windows', '--quiet', '--no-cache', '--link', str(library), '--output', str(project / 'program.exe')], check=True, timeout=300)
        subprocess.run(['wine', str(project / 'program.exe')], env={**os.environ, 'WINEDEBUG': '-all'}, check=True, timeout=120)
        results.append('Wine Win32')
    if sys.platform in ('darwin', 'win32'):
        # Native Cocoa or Win32 through the C bridge, on a real desktop host.
        project = work / 'native'
        project.mkdir()
        (project / 'main.dyn').write_text(SOURCE, encoding='utf-8')
        if sys.platform == 'win32' and os.environ.get('DYN_OPENGL_DLL'):
            # Match the rendering/event fixtures on software-only Windows runners.
            driver = Path(os.environ['DYN_OPENGL_DLL']).resolve()
            shutil.copy2(driver, project / 'opengl32.dll')
            shutil.copy2(driver.parent / 'libgallium_wgl.dll', project / 'libgallium_wgl.dll')
        bridge = project / ('libdyn_window.dylib' if sys.platform == 'darwin' else 'dyn_window.dll')
        subprocess.run([sys.executable, str(ROOT / 'vendor/window/native/build.py'), '--output', str(bridge)], check=True, timeout=180)
        library = bridge if sys.platform == 'darwin' else project / 'libdyn_window.dll.a'
        program = project / ('program.exe' if sys.platform == 'win32' else 'program')
        subprocess.run([DYN, 'build', str(project), '--quiet', '--no-cache', '--link', str(library), '--output', str(program)], check=True, timeout=300)
        subprocess.run([str(program)], check=True, timeout=120)
        results.append('Cocoa' if sys.platform == 'darwin' else 'Win32')
    for target in ('aarch64-macos', 'x86_64-windows', 'aarch64-windows'):
        project = work / ('cross-' + target)
        project.mkdir()
        (project / 'main.dyn').write_text(SOURCE, encoding='utf-8')
        subprocess.run([DYN, 'build', str(project), '--target', target, '--quiet', '--no-cache', '--emit-object', '--no-link', '--output', str(project / 'program')], check=True, timeout=300)
COMPOSITION_C = r'''
#include "desktop_common.h"
#include <assert.h>
int main(void) {
  dyn_window_composition c;
  uint8_t text[300];
  for (int i = 0; i < 300; i += 3) { text[i] = 0xe3; text[i + 1] = 0x81; text[i + 2] = 0x82; }
  composition_store(&c, text, 300, 9, 400);
  assert(c.text_length == 255 && c.active && c.cursor_begin == 9 && c.cursor_end == 255);
  composition_store(&c, (const uint8_t *)"ab", 2, -1, 1);
  assert(c.text_length == 2 && c.cursor_begin == -1 && c.cursor_end == 1);
  composition_store(&c, (const uint8_t *)"", 0, 0, 0);
  assert(!c.active);
  return 0;
}
'''
if shutil.which('cc'):
    with tempfile.TemporaryDirectory(prefix='dyn-composition-') as directory:
        source = Path(directory) / 'composition.c'
        source.write_text(COMPOSITION_C, encoding='utf-8')
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I' + str(ROOT / 'vendor/window/native'), str(source), '-o', str(Path(directory) / 'composition')], check=True, timeout=60)
        subprocess.run([str(Path(directory) / 'composition')], check=True, timeout=30)
    print('PASS portable composition snapshots without a display')
if not results:
    print('SKIP window desktop runtime: no display backend available; cross-builds passed')
else:
    print('PASS window desktop: composition snapshots and text input placement, clipboard round trip, cursors, scale, wait and box_input on ' + ', '.join(results) + '; macOS and Windows ARM64 cross-build')
