#!/usr/bin/env python3
"""IME interaction: consumed keys, owned redraw state and final caret geometry."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use "std/ui/box" box
use "std/ui" ui
use "std/mem" mem
use "std/bytes" bytes
use "std/unicode/utf8" utf8
fn check(ok: bool, why: []const u8) { if !ok { #panic(why) } }
fn measure(data: rawptr, text: []const u8) f32 {
  _ = data
  check(utf8.valid(text), "measure receives complete UTF8")
  return #cast(f32, utf8.codepoint_count(text).value) * 8.0
}
struct App { storage: [64]u8, edit: box.Edit, field: *box.Box, submitted: bool, x: f32 }
fn frame(state: *box.State, arena: *mem.Arena, app: *App, input: box.Input) {
  mem.arena_reset(arena)
  context := ui.Context{}
  ui.begin(&context, arena, ui.Input{}, ui.Rect{width:400,height:200})
  box.begin(state, arena, input, 400.0, 200.0, 0.02)
  panel := box.build(state, box.AbsoluteX | box.AbsoluteY, "panel")
  panel.floating = [app.x,20.0]
  panel.width = box.pixels(300.0,1.0)
  panel.height = box.pixels(100.0,1.0)
  box.push_parent(state,panel)
  result := box.text_field(state,"field",app.storage[..],&app.edit)
  app.field = result.signal.box
  app.submitted = result.submitted
  _ = box.button(state,"button")
  box.pop_parent(state)
  box.end(state,&context)
  ui.end(&context)
}
fn main() {
  persistent := mem.arena_create(0)
  arena := mem.arena_create(0)
  defer { mem.arena_release(arena)
    mem.arena_release(persistent) }
  state := box.create(persistent,measure,nil,16.0)
  app := App{}
  frame(state,arena,&app,box.Input{})
  frame(state,arena,&app,box.Input{tab:true})
  frame(state,arena,&app,box.Input{text:"ab"})
  focus := state.focused
  check(focus == app.field.key && app.edit.cursor == 2,"focused typed buffer")
  preedit: [3]u8 = [0xe3,0x81,0x8b]
  input := box.Input{composition:preedit[..],composition_cursor:3,composition_handled:true}
  check(box.needs_frame(state,input),"preedit starts redraw")
  frame(state,arena,&app,input)
  check(!box.needs_frame(state,input),"unchanged preedit stays idle")
  preedit[2] = 0x8d
  check(box.needs_frame(state,input),"borrowed bytes changed require redraw")
  frame(state,arena,&app,input)
  check(!box.needs_frame(state,input),"updated preedit settles")
  input.composition_cursor = 1
  frame(state,arena,&app,input)
  check(app.edit.length == 2,"preedit does not insert")
  // Byte1 lies inside a three-byte code point; never measure a broken prefix.
  check(state.text_input_rect[0] == app.field.rect[0] + 20.0,"cursor clamps to UTF8 boundary")
  frame(state,arena,&app,box.Input{composition:preedit[..],composition_cursor:3,backspace:true,left:true,enter:true,escape:true,tab:true})
  check(bytes.equal(app.storage[..app.edit.length],"ab") && app.edit.cursor == 2 && !app.submitted && state.focused == focus,"active IME owns keys")
  frame(state,arena,&app,box.Input{home:true})
  frame(state,arena,&app,box.Input{right:true})
  frame(state,arena,&app,input)
  check(bytes.equal(app.field.text,"aきb") && bytes.equal(app.storage[..app.edit.length],"ab"),"preedit preview shifts suffix without insertion")
  frame(state,arena,&app,box.Input{select_all:true})
  frame(state,arena,&app,input)
  check(bytes.equal(app.field.text,"き") && app.edit.length == 2,"preedit previews selection replacement")
  frame(state,arena,&app,box.Input{end:true})
  // The final Backspace may clear preedit in the same native poll.
  frame(state,arena,&app,box.Input{composition_handled:true,backspace:true,delete:true,home:true,select_all:true,cut:true,escape:true,tab:true,enter:true})
  check(bytes.equal(app.storage[..app.edit.length],"ab") && app.edit.cursor == 2 && !app.submitted && state.focused == focus,"ending IME owns final poll")
  frame(state,arena,&app,box.Input{composition_handled:true,text:"é",enter:true})
  check(bytes.equal(app.storage[..app.edit.length],"abé") && !app.submitted,"committed text inserts despite consumed Enter")
  frame(state,arena,&app,box.Input{enter:true})
  check(app.submitted,"ordinary Enter still submits")
  app.x = 70.0
  frame(state,arena,&app,box.Input{})
  check(state.text_input_rect[0] == 98.0 && state.text_input_rect[1] == 25.0,"candidate rectangle follows current layout")
  frame(state,arena,&app,box.Input{backspace:true})
  check(bytes.equal(app.storage[..app.edit.length],"ab"),"ordinary editing resumes")
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-ui-ime-') as directory:
    work=Path(directory)
    (work/'main.dyn').write_text(SOURCE,encoding='utf-8')
    for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
        output=work/'test'
        subprocess.run([DYN,'build',str(work),*flags,'--quiet','--output',str(output)],check=True,timeout=120)
        subprocess.run([str(output)],check=True,timeout=30)
    for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows','wasm32-wasi'):
        output=work/target
        subprocess.run([DYN,'build',str(work),'--release','--target',target,'--quiet','--output',str(output)],check=True,timeout=120)
        emulator={'aarch64-linux':'qemu-aarch64','riscv64-linux':'qemu-riscv64','x86_64-windows':'wine'}.get(target)
        if emulator and shutil.which(emulator): subprocess.run([emulator,str(output)],check=True,timeout=60)
print('PASS box IME: consumed ending keys, commit insertion, UTF8 caret, owned change-driven redraw and final layout placement (debug/O2/O3 and cross-targets)')
