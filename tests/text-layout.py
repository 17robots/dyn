#!/usr/bin/env python3
"""Portable Latin layout, Unicode breaking, positioned-glyph UI rendering."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use "std/text/layout" layout
use "std/ui" ui
use "std/ui/text" ui_text
use "std/ui/software" software
use "std/mem" mem
use "std/errors" errors
use "std/bytes" bytes
fn check(ok: bool) { if !ok { #panic("layout contract") } }
fn advance(raw: rawptr, cp: u32) f64 {
  _ = raw
  if cp == 32 { return 5.0 }
  return 10.0
}
fn kern(raw: rawptr, left, right: u32) f64 {
  _ = raw
  if raw != nil && left == 97 && right == 45 { return 5.0 }
  if left == 65 && right == 86 { return -2.0 }
  return 0.0
}
coverage: [1]u8 = [255]
fn glyph(raw: rawptr, cp: u32) software.Glyph {
  _ = raw
  _ = cp
  return software.Glyph{ pixels: coverage[..], width: 1, height: 1, stride: 1, advance: 10 }
}
fn big_advance(raw: rawptr, cp: u32) f64 { _ = raw
  _ = cp
  return 2000000000.0 }
fn big_glyph(raw: rawptr, cp: u32) software.Glyph { _ = raw
  _ = cp
  return software.Glyph{ pixels: coverage[..], width: 1, height: 1, stride: 1, x_offset: -2147483647, advance: 10 } }
fn main() {
  arena := mem.Arena{}
  defer { mem.arena_release(&arena) }
  font := layout.Font{ advance: advance, kerning: kern, line_height: 12 }
  result := layout.build(&arena, "AV AV", font, layout.Options{ width: 30 })
  check(result.ok && #len(result.value.lines) == 2 && #len(result.value.glyphs) == 4)
  check(result.value.lines[0].width == 18.0 && result.value.lines[1].width == 18.0 && result.value.height == 24.0)
  check(result.value.glyphs[1].x == 8.0 && result.value.glyphs[2].x == 0.0 && result.value.glyphs[2].y == 12.0)
  context := ui.Context{}
  ui.begin(&context, &arena, ui.Input{}, ui.Rect{ width: 32, height: 32 })
  ui_text.label(&context, ui.Rect{ x: 2, y: 3, width: 28, height: 28 }, &result.value, ui.Color{ r: 255, a: 255 })
  ui.end(&context)
  pixels: [4096]u8 = []
  surface := software.Surface{ pixels: pixels[..], width: 32, height: 32, stride: 128 }
  check(software.render(&surface, ui.first(&context), software.Font{ glyph: glyph, line_height: 12 }).ok)
  check(pixels[(3 * 32 + 2) * 4] == 255 && pixels[(3 * 32 + 10) * 4] == 255 && pixels[(15 * 32 + 2) * 4] == 255)
  result = layout.build(&arena, "AV", font, layout.Options{ width: 30, alignment: layout.Align.Center })
  check(result.ok && result.value.glyphs[0].x == 6.0 && result.value.glyphs[1].x == 14.0)
  result = layout.build(&arena, "AV", font, layout.Options{ width: 30, alignment: layout.Align.Right })
  check(result.ok && result.value.glyphs[0].x == 12.0)
  result = layout.build(&arena, "A\tV", font, layout.Options{})
  check(result.ok && result.value.width == 30.0 && result.value.glyphs[1].x == 20.0)
  result = layout.build(&arena, "A\r\n\nB\n", font, layout.Options{})
  check(result.ok && #len(result.value.lines) == 4 && result.value.height == 48.0 && #len(result.value.glyphs) == 2)
  result = layout.build(&arena, "A\xcc\x8a", font, layout.Options{})
  check(result.ok && bytes.equal(result.value.text, "\xc3\x85") && #len(result.value.glyphs) == 1 && result.value.glyphs[0].end == 2)
  result = layout.build(&arena, "A\xcc\x8aV", font, layout.Options{ width: 12, normalize: false })
  check(result.ok && #len(result.value.lines) == 2 && #len(result.value.glyphs) == 3)
  check(result.value.glyphs[0].start == 0 && result.value.glyphs[0].end == 3 && result.value.glyphs[1].start == 0 && result.value.glyphs[1].end == 3)
  check(result.value.glyphs[1].y == 0.0 && result.value.glyphs[2].y == 12.0)
  result = layout.build(&arena, "abcde", font, layout.Options{ width: 21 })
  check(result.ok && #len(result.value.lines) == 3 && result.value.lines[2].width == 10.0)
  result = layout.build(&arena, "", font, layout.Options{})
  check(result.ok && #len(result.value.lines) == 1 && #len(result.value.glyphs) == 0)
  result = layout.build(&arena, "ab\xc2\xadc", font, layout.Options{})
  check(result.ok && #len(result.value.glyphs) == 3 && result.value.width == 30.0)
  result = layout.build(&arena, "a\xc2\xadbcd", font, layout.Options{ width: 25 })
  check(result.ok && result.value.glyphs[1].codepoint == 45 && result.value.glyphs[1].y == 0.0 && result.value.glyphs[2].y == 12.0)
  result = layout.build(&arena, "a\xc2\xadbc", font, layout.Options{ width: 15 })
  check(result.ok && result.value.lines[0].width == 10.0 && result.value.glyphs[1].codepoint != 45)
  state: i32 = 0
  font.data = &state
  result = layout.build(&arena, "a\xc2\xadbc", font, layout.Options{ width: 20 })
  check(result.ok && result.value.lines[0].width == 20.0 && result.value.glyphs[1].codepoint == 98)
  font.data = nil
  result = layout.build(&arena, "a\xc2\xad bc", font, layout.Options{ width: 25 })
  check(result.ok && result.value.lines[0].glyph_count == 1 && result.value.glyphs[0].codepoint == 97)
  result = layout.build(&arena, "AAA", layout.Font{ advance: big_advance, line_height: 1 }, layout.Options{})
  check(result.ok && result.value.glyphs[2].x == 4000000000.0)
  ui.begin(&context, &arena, ui.Input{}, ui.Rect{ width: 32, height: 32 })
  ui_text.label(&context, ui.Rect{ width: 32, height: 32 }, &result.value, ui.Color{ r: 255, a: 255 })
  ui.end(&context)
  for i in 0..#len(pixels) { pixels[i] = 0 }
  check(software.render(&surface, ui.first(&context), software.Font{ glyph: big_glyph, line_height: 1 }).ok && pixels[0] == 0)
  ui.begin(&context, &arena, ui.Input{}, ui.Rect{ width: 32, height: 32 })
  ui.glyph(&context, ui.Rect{ width: 32, height: 32 }, 65, 2147483648, 0, ui.Color{ r: 255, a: 255 })
  ui.end(&context)
  check(software.render(&surface, ui.first(&context), software.Font{ glyph: big_glyph, line_height: 1 }).ok && pixels[4] == 255)
  before := mem.arena_mark(&arena)
  bad := layout.build(&arena, "ok\xff", font, layout.Options{})
  check(!bad.ok && bad.kind == errors.Kind.InvalidInput && bad.offset == 2 && mem.arena_mark(&arena) == before)
  bad = layout.build(&arena, "x", layout.Font{}, layout.Options{})
  check(!bad.ok && mem.arena_mark(&arena) == before)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-layout-') as directory:
    work=Path(directory);(work/'main.dyn').write_text(SOURCE)
    for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
        output=work/'program'
        subprocess.run([DYN,'build',str(work),*flags,'--quiet','--no-cache','--output',str(output)],check=True,timeout=300)
        subprocess.run([str(output)],check=True,timeout=30)
    for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows','wasm32-wasi'):
        output=work/target
        subprocess.run([DYN,'build',str(work),'--target',target,'--release','--quiet','--output',str(output)],check=True,timeout=300)
        emulator={'aarch64-linux':'qemu-aarch64','riscv64-linux':'qemu-riscv64','x86_64-windows':'wine'}.get(target)
        if emulator and shutil.which(emulator): subprocess.run([emulator,str(output)],check=True,timeout=60)
        if target=='wasm32-wasi' and shutil.which('node'):
            script="const {WASI}=require('node:wasi'),fs=require('fs');(async()=>{const wasi=new WASI({version:'preview1',returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});"
            subprocess.run(['node','--no-warnings','-e',script,str(output)],check=True,timeout=60)
print('PASS text layout: pair kerning, normalization, Unicode/grapheme wrapping, alignment, tabs, newlines, soft hyphens, UI draw and rollback')
