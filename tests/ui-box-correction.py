#!/usr/bin/env python3
"""Owned native Edit chunks through a focused textbox with revision guards."""
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
use "std/text/edit" edit
use "std/errors" errors
use "std/bytes" bytes
use "vendor/window/events" events
fn check(ok: bool, why: []const u8) { if !ok { #panic(why) } }
fn measure(data: rawptr, text: []const u8) f32 { _ = data
  return #cast(f32,#len(text))*8.0 }
struct App { storage: [64]u8, edit: box.Edit, changed: bool, error: errors.Kind }
fn frame(state: *box.State, arena: *mem.Arena, app: *App, input: box.Input) {
  mem.arena_reset(arena)
  context := ui.Context{}
  ui.begin(&context,arena,ui.Input{},ui.Rect{width:400,height:200})
  box.begin(state,arena,input,400.0,200.0,0.02)
  result := box.text_field(state,"field",app.storage[..],&app.edit)
  app.changed = result.changed
  app.error = result.correction_error
  _ = box.button(state,"other")
  box.end(state,&context)
  ui.end(&context)
}
fn correction(collector: *events.EditBuffer, token: u64, start, end: i32, text: []const u8) edit.Replacement {
  event := events.Event{kind:events.Kind.Edit,key:#cast(u32,token & 4294967295),modifiers:#cast(u32,token>>32),x:start,y:end,width:#cast(i32,#len(text)),text_length:#cast(u32,#len(text)),button:1}
  for i in 0..#len(text) { event.text[i] = text[i] }
  result := events.collect_edit(collector,&event)
  check(result.ok && result.ready,"native edit assembly")
  return result.value
}
fn main() {
  persistent := mem.Arena{}
  arena := mem.Arena{}
  defer { mem.arena_release(&arena)
    mem.arena_release(&persistent) }
  state := box.create(&persistent,measure,nil,16.0)
  app := App{}
  collector := events.EditBuffer{}
  frame(state,&arena,&app,box.Input{})
  frame(state,&arena,&app,box.Input{tab:true})
  frame(state,&arena,&app,box.Input{text:"teh cat"})
  published := state.text_context.token
  check(published != 0 && bytes.equal(state.text_context.text,"teh cat"),"focused context publication")
  frame(state,&arena,&app,box.Input{})
  check(state.text_context.token == published,"idle redraw keeps context token")
  change := correction(&collector,published,0,3,"the")
  frame(state,&arena,&app,box.Input{correction:&change})
  check(app.changed && app.error == errors.Kind.None && bytes.equal(app.storage[..app.edit.length],"the cat") && app.edit.cursor == 3,"owned edit reaches widget")
  check(state.text_context.token != published && state.text_context.cause == edit.Cause.InputMethod,"correction publishes fresh IME context")
  frame(state,&arena,&app,box.Input{correction:&change})
  check(!app.changed && app.error == errors.Kind.InvalidState && bytes.equal(app.storage[..app.edit.length],"the cat"),"replay does not change buffer")
  published = state.text_context.token
  change = correction(&collector,published,0,3,"bad")
  frame(state,&arena,&app,box.Input{left:true})
  frame(state,&arena,&app,box.Input{correction:&change})
  check(app.error == errors.Kind.InvalidState && bytes.equal(app.storage[..app.edit.length],"the cat"),"selection change invalidates pending edit")
  published = state.text_context.token
  change = correction(&collector,published,0,3,"bad")
  app.storage[0] = 'T'
  frame(state,&arena,&app,box.Input{correction:&change})
  check(app.error == errors.Kind.InvalidState && app.storage[0] == 'T',"external document change invalidates edit")
  published = state.text_context.token
  frame(state,&arena,&app,box.Input{tab:true})
  check(state.text_context.token == 0,"leaving text focus removes publication")
  frame(state,&arena,&app,box.Input{tab:true,shift:true})
  check(state.text_context.token != published,"returning focus gets fresh publication")
  change = correction(&collector,state.text_context.token,0,0,"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
  frame(state,&arena,&app,box.Input{correction:&change})
  check(!app.changed && app.error == errors.Kind.Capacity && bytes.equal(app.storage[..app.edit.length],"The cat"),"capacity failure is atomic")
  change = correction(&collector,state.text_context.token,0,1,"A\nB")
  frame(state,&arena,&app,box.Input{correction:&change})
  check(app.error == errors.Kind.InvalidInput && app.storage[0] == 'T',"single line rejects multiline correction")
  change = correction(&collector,state.text_context.token,0,1,"Z")
  frame(state,&arena,&app,box.Input{correction:&change,text:"extra",tab:true})
  check(app.error == errors.Kind.InvalidInput && bytes.equal(app.storage[..app.edit.length],"The cat") && state.text_context.token != 0,"unordered combined input rejected without moving focus")
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-ui-correction-') as directory:
    work=Path(directory)
    (work/'main.dyn').write_text(SOURCE,encoding='utf-8')
    for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
        output=work/'test'
        subprocess.run([DYN,'build',str(work),*flags,'--quiet','--output',str(output)],check=True,timeout=180)
        subprocess.run([str(output)],check=True,timeout=60)
    for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows','wasm32-wasi'):
        output=work/target
        subprocess.run([DYN,'build',str(work),'--release','--target',target,'--quiet','--output',str(output)],check=True,timeout=180)
        emulator={'aarch64-linux':'qemu-aarch64','riscv64-linux':'qemu-riscv64','x86_64-windows':'wine'}.get(target)
        if emulator and shutil.which(emulator): subprocess.run([emulator,str(output)],check=True,timeout=90)
print('PASS widget corrections: owned native transaction, revision/cursor/focus/external-data guards, capacity atomicity, and cause publication (debug/O2/O3, cross-targets)')
