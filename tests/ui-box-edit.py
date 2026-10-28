#!/usr/bin/env python3
"""UTF-8 text selection, word editing, focus traversal and layout-only API."""
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
SOURCE = r'''use "std/ui/box" box
use "std/ui" ui
use "std/mem" mem
use "std/bytes" bytes
use "std/unicode/utf8" utf8
fn check(ok: bool, why: []const u8) { if !ok { #panic(why) } }
fn measure(data: rawptr, text: []const u8) f32 {
  _ = data
  return #cast(f32, utf8.codepoint_count(text).value) * 8.0
}
struct App { storage: [64]u8, edit: box.Edit, field: *box.Box, button: *box.Box, clicked: bool }
fn frame(state: *box.State, arena: *mem.Arena, app: *App, input: box.Input) {
  mem.arena_reset(arena)
  box.begin(state, arena, input, 400.0, 200.0, 0.02)
  result := box.text_field(state, "field", app.storage[..], &app.edit)
  app.field = result.signal.box
  app.field.width = box.pixels(64.0, 1.0)
  button := box.button(state, "button")
  app.button = button.box
  app.clicked = button.clicked
  box.layout(state)
}
fn main() {
  persistent := mem.arena_create(0)
  arena := mem.arena_create(0)
  defer { mem.arena_release(arena)
    mem.arena_release(persistent) }
  state := box.create(persistent, measure, nil, 16.0)
  app := App{}
  initial := "héllo world"
  _ = mem.copy(app.storage[..#len(initial)], initial)
  app.edit.length = #len(initial)
  frame(state, arena, &app, box.Input{})
  frame(state, arena, &app, box.Input{ tab: true })
  check(state.focused == app.field.key, "tab first")
  frame(state, arena, &app, box.Input{ end: true })
  check(app.edit.cursor == 12 && app.edit.scroll_x > 0.0, "end scrolls caret")
  frame(state, arena, &app, box.Input{ left: true, control: true, shift: true })
  check(app.edit.cursor == 7 && app.edit.anchor == 12 && app.edit.selecting, "select word")
  check(app.field.selection[1] > app.field.selection[0], "selection paints")
  frame(state, arena, &app, box.Input{ copy: true })
  check(bytes.equal(state.copied, "world"), "copy selection")
  frame(state, arena, &app, box.Input{ text: "世界" })
  check(bytes.equal(app.storage[..app.edit.length], "héllo 世界") && !app.edit.selecting, "replace selection")
  frame(state, arena, &app, box.Input{ home: true })
  check(app.edit.scroll_x == 0.0, "home reveals start")
  frame(state, arena, &app, box.Input{ right: true, shift: true })
  frame(state, arena, &app, box.Input{ right: true, shift: true })
  check(app.edit.cursor == 3 && app.edit.anchor == 0, "utf8 selection")
  frame(state, arena, &app, box.Input{ cut: true })
  check(bytes.equal(state.copied, "hé") && bytes.equal(app.storage[..app.edit.length], "llo 世界"), "cut selection")
  frame(state, arena, &app, box.Input{ select_all: true })
  frame(state, arena, &app, box.Input{ paste: true, clipboard: "a\nb" })
  check(bytes.equal(app.storage[..app.edit.length], "llo 世界"), "reject multiline without deleting selection")
  frame(state, arena, &app, box.Input{ text: "12345678901234567890123456789012345678901234567890123456789012345" })
  check(bytes.equal(app.storage[..app.edit.length], "llo 世界"), "reject oversized replacement atomically")
  frame(state, arena, &app, box.Input{ paste: true, clipboard: "hello world" })
  frame(state, arena, &app, box.Input{ backspace: true, control: true })
  check(bytes.equal(app.storage[..app.edit.length], "hello "), "word backspace")
  frame(state, arena, &app, box.Input{ home: true })
  frame(state, arena, &app, box.Input{ delete: true, control: true })
  check(app.edit.length == 0, "word delete")
  frame(state, arena, &app, box.Input{ text: "héllo" })
  frame(state, arena, &app, box.Input{ home: true })
  // Movement and release can arrive in one poll without a held-drag frame.
  frame(state, arena, &app, box.Input{ x: 5.0, y: 8.0 })
  frame(state, arena, &app, box.Input{ x: 5.0, y: 8.0, down: true })
  frame(state, arena, &app, box.Input{ x: 20.0, y: 8.0 })
  check(app.edit.selecting && app.edit.anchor == 0 && app.edit.cursor == 3, "release position selection")
  // Hover then press at the first character; drag across a multibyte glyph.
  frame(state, arena, &app, box.Input{ x: 5.0, y: 8.0 })
  frame(state, arena, &app, box.Input{ x: 5.0, y: 8.0, down: true })
  frame(state, arena, &app, box.Input{ x: 20.0, y: 8.0, down: true })
  check(app.edit.selecting && app.edit.anchor == 0 && app.edit.cursor == 3, "mouse utf8 selection")
  frame(state, arena, &app, box.Input{})
  frame(state, arena, &app, box.Input{ select_all: true })
  frame(state, arena, &app, box.Input{ text: "abcdef" })
  frame(state, arena, &app, box.Input{ home: true })
  frame(state, arena, &app, box.Input{ right: true, shift: true })
  frame(state, arena, &app, box.Input{ right: true, shift: true })
  frame(state, arena, &app, box.Input{ right: true, shift: true })
  frame(state, arena, &app, box.Input{ paste: true, clipboard: app.storage[..2] })
  check(bytes.equal(app.storage[..app.edit.length], "abdef"), "aliased selected paste")
  frame(state, arena, &app, box.Input{ tab: true })
  check(state.focused == app.button.key, "tab next")
  frame(state, arena, &app, box.Input{ enter: true })
  check(app.clicked, "keyboard activation")
  frame(state, arena, &app, box.Input{ tab: true })
  check(state.focused == app.field.key, "tab wraps")
  frame(state, arena, &app, box.Input{ tab: true, shift: true })
  check(state.focused == app.button.key, "reverse tab")
  // Container padding and screen-absolute children, consumed by custom renderers.
  mem.arena_reset(arena)
  box.begin(state, arena, box.Input{}, 300.0, 200.0, 0.02)
  panel := box.build(state, box.GreedyShrink, "panel")
  panel.width = box.pixels(100.0, 1.0)
  panel.height = box.pixels(60.0, 1.0)
  panel.padding = [10.0, 5.0]
  box.push_parent(state, panel)
  flexible := box.build(state, 0, "flex")
  flexible.width = box.percent(1.0, 1.0)
  flexible.height = box.pixels(50.0, 0.0)
  footer := box.build(state, 0, "footer")
  footer.width = box.percent(1.0, 1.0)
  footer.height = box.pixels(20.0, 1.0)
  absolute := box.build(state, box.AbsoluteX | box.AbsoluteY | box.Clickable, "absolute")
  absolute.floating = [150.0, 100.0]
  absolute.width = box.pixels(20.0, 1.0)
  absolute.height = box.pixels(10.0, 1.0)
  box.pop_parent(state)
  box.layout(state)
  check(flexible.size[0] == 80.0 && flexible.size[1] == 30.0, "inner width and greedy shrink")
  check(flexible.rect[0] == 10.0 && flexible.rect[1] == 5.0 && footer.rect[1] == 35.0, "padding geometry")
  check(absolute.rect[0] == 150.0 && absolute.rect[1] == 100.0, "screen absolute")
  check(box.hit(state, 155.0, 105.0) == absolute.key, "unclipped absolute child hit")
  context := ui.Context{}
  ui.begin(&context, arena, ui.Input{}, ui.Rect{ width: 300, height: 200 })
  box.render(state, &context)
  ui.end(&context)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-box-edit-') as directory:
    work = Path(directory)
    (work/'main.dyn').write_text(SOURCE)
    for mode in ('--debug', '--release'):
        output = work/'test'
        subprocess.run([DYN, 'build', str(work), mode, '--quiet', '--output', str(output)], check=True, timeout=300)
        subprocess.run([str(output)], check=True, timeout=90)
    for target in ('aarch64-linux', 'riscv64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows', 'wasm32-wasi'):
        output = work/target
        subprocess.run([DYN, 'build', str(work), '--release', '--target', target, '--quiet', '--output', str(output)], check=True, timeout=300)
        emulator = {'aarch64-linux':'qemu-aarch64', 'riscv64-linux':'qemu-riscv64', 'x86_64-windows':'wine'}.get(target)
        if emulator and shutil.which(emulator):
            subprocess.run([emulator, str(output)], check=True, timeout=120)
        if target == 'wasm32-wasi' and shutil.which('node'):
            script = "const {WASI}=require('node:wasi'),fs=require('node:fs');(async()=>{const wasi=new WASI({version:'preview1',returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});"
            subprocess.run(['node','--no-warnings','-e',script,str(output)],check=True,timeout=120)
print('PASS box editing: mouse/keyboard UTF-8 selection, Unicode word edits, atomic replacement, scroll, focus traversal, activation and custom layout geometry')
