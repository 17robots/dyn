#!/usr/bin/env python3
"""Immediate-mode state, owned draw commands and portable RGBA raster output."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/ui" ui
use "std/ui/software" software
use "std/mem" mem
use "std/errors" errors
fn check(ok: bool) { if !ok { #panic("UI contract") } }
fn pair(context: *ui.Context, arena: *mem.Arena, input: ui.Input) [2]ui.Response {
  mem.arena_rewind(arena, 0)
  ui.begin(context, arena, input, ui.Rect{ width: 100, height: 60 })
  a := ui.button(context, 1, ui.Rect{ width: 10, height: 10 }, "one", true)
  b := ui.button(context, 2, ui.Rect{ x: 20, width: 10, height: 10 }, "two", true)
  ui.end(context)
  return [a, b]
}
fn interactions(arena: *mem.Arena) {
  context := ui.Context{}
  check(context.style.background.a == 255 && context.style.padding == 4)
  response := pair(&context, arena, ui.Input{ x: 5, y: 5, released: true })
  check(!response[0].activated)
  response = pair(&context, arena, ui.Input{ x: 5, y: 5, down: true })
  check(response[0].held && context.active == 1)
  response = pair(&context, arena, ui.Input{ x: 25, y: 5, down: true })
  check(response[0].held && response[1].hovered && !response[1].held)
  response = pair(&context, arena, ui.Input{ x: 25, y: 5 })
  check(!response[0].activated && !response[1].activated && context.active == 0)
  response = pair(&context, arena, ui.Input{ x: 5, y: 5, down: true })
  response = pair(&context, arena, ui.Input{ x: 5, y: 5 })
  check(response[0].activated && !response[1].activated)
  response = pair(&context, arena, ui.Input{ x: 5, y: 5 })
  check(!response[0].activated)
  response = pair(&context, arena, ui.Input{ x: 5, y: 5, pressed: true, released: true })
  check(response[0].activated && context.active == 0)
  context = ui.Context{}
  response = pair(&context, arena, ui.Input{ tab: true })
  check(context.focused == 1)
  response = pair(&context, arena, ui.Input{ tab: true })
  check(context.focused == 2)
  response = pair(&context, arena, ui.Input{ tab: true })
  check(context.focused == 1)
  response = pair(&context, arena, ui.Input{ activate: true })
  check(response[0].activated && !response[1].activated)
  ui.begin(&context, arena, ui.Input{}, ui.Rect{ width: 100, height: 60 })
  ui.end(&context)
  check(context.focused == 0)
  response = pair(&context, arena, ui.Input{ x: 5, y: 5, down: true })
  ui.begin(&context, arena, ui.Input{ x: 5, y: 5, down: true }, ui.Rect{ width: 100, height: 60 })
  disabled := ui.button(&context, 1, ui.Rect{ width: 10, height: 10 }, "", false)
  ui.end(&context)
  check(!disabled.held && context.active == 0 && context.focused == 0)
  ui.begin(&context, arena, ui.Input{ x: 5, y: 5, pressed: true }, ui.Rect{ width: 100, height: 60 })
  clip := ui.push_clip(&context, ui.Rect{ width: 3, height: 3 })
  hidden := ui.button(&context, 1, ui.Rect{ width: 10, height: 10 }, "", true)
  ui.pop_clip(&context, clip)
  ui.end(&context)
  check(!hidden.hovered && context.active == 0)
}
fn widgets(arena: *mem.Arena) {
  context := ui.Context{}
  toggled := false
  ui.begin(&context, arena, ui.Input{ x: 3, y: 3, pressed: true, released: true }, ui.Rect{ width: 100, height: 60 })
  checkbox := ui.checkbox(&context, 1, ui.Rect{ width: 40, height: 12 }, "on", &toggled, true)
  ui.end(&context)
  check(toggled && checkbox.changed)
  value: i32 = 0
  context = ui.Context{}
  ui.begin(&context, arena, ui.Input{ x: 20, y: 5, down: true }, ui.Rect{ width: 100, height: 60 })
  response := ui.slider(&context, 9, ui.Rect{ width: 21, height: 10 }, &value, -2147483648, 2147483647, true)
  ui.end(&context)
  check(response.changed && value == 2147483647)
  ui.begin(&context, arena, ui.Input{ x: -100, y: 5, down: true }, ui.Rect{ width: 100, height: 60 })
  response = ui.slider(&context, 9, ui.Rect{ width: 21, height: 10 }, &value, -2147483648, 2147483647, true)
  ui.end(&context)
  check(value == -2147483648 && response.changed)
  ui.begin(&context, arena, ui.Input{ right: true }, ui.Rect{ width: 100, height: 60 })
  response = ui.slider(&context, 9, ui.Rect{ width: 21, height: 10 }, &value, -2147483648, 2147483647, true)
  ui.end(&context)
  check(value == -2147483647 && response.changed)
  value = 100
  ui.begin(&context, arena, ui.Input{}, ui.Rect{ width: 100, height: 60 })
  response = ui.slider(&context, 9, ui.Rect{ width: 21, height: 10 }, &value, 0, 10, false)
  ui.end(&context)
  check(value == 100 && !response.changed)
}
coverage: [4]u8 = [255, 128, 0, 255]
struct Trace { calls: usize, first: u32, last: u32, invalid: bool, bearing: i32 }
fn glyph(raw: rawptr, codepoint: u32) software.Glyph {
  trace := #cast(*Trace, raw)
  if trace.calls == 0 { trace.first = codepoint }
  trace.calls += 1
  trace.last = codepoint
  pixels: []const u8 = coverage[..]
  if trace.invalid { pixels = pixels[..3] }
  return software.Glyph{ pixels: pixels, width: 2, height: 2, stride: 2, advance: 3, x_offset: trace.bearing }
}
fn raster(arena: *mem.Arena) {
  context := ui.Context{}
  bytes: [80]u8 = []
  for i in 0..80 { bytes[i] = 109 }
  for y in 0..4 { for x in 0..16 { bytes[y * 20 + x] = 0 } }
  surface := software.Surface{ pixels: bytes[..], width: 4, height: 4, stride: 20 }
  trace := Trace{}
  font := software.Font{ data: &trace, glyph: glyph, line_height: 3 }
  ui.begin(&context, arena, ui.Input{}, ui.Rect{ width: 4, height: 4 })
  ui.rectangle(&context, ui.Rect{ x: -2147483648, y: -2147483648, width: 1, height: 1 }, ui.Color{ a: 255 })
  ui.rectangle(&context, ui.Rect{ width: 4, height: 4 }, ui.Color{ r: 200, a: 128 })
  ui.rectangle(&context, ui.Rect{ x: 1, width: 2, height: 2 }, ui.Color{ b: 200, a: 255 })
  ui.rectangle(&context, ui.Rect{ x: 1, width: 2, height: 2 }, ui.Color{ r: 200, a: 128 })
  ui.end(&context)
  check(software.render(&surface, ui.first(&context), font).ok)
  check(bytes[0] == 200 && bytes[3] == 128)
  check(bytes[4] == 100 && bytes[6] == 100 && bytes[7] == 255)
  for y in 0..4 { for x in 16..20 { check(bytes[y * 20 + x] == 109) } }
  for i in 0..80 { bytes[i] = 0 }
  mutable: [4]u8 = [65, 10, 65, 33]
  ui.begin(&context, arena, ui.Input{}, ui.Rect{ width: 4, height: 4 })
  ui.label(&context, ui.Rect{ width: 2, height: 4 }, mutable[..3], ui.Color{ g: 240, a: 128 })
  mutable[0] = 66
  ui.end(&context)
  check(ui.first(&context).text[0] == 65)
  check(software.render(&surface, ui.first(&context), font).ok)
  check(bytes[1] == 240 && bytes[3] == 128 && bytes[7] == 64 && bytes[23] == 0 && bytes[27] == 128)
  check(bytes[61] == 240 && bytes[63] == 128 && trace.calls == 2)
  for i in 0..80 { bytes[i] = 0 }
  trace = Trace{ bearing: -1 }
  ui.begin(&context, arena, ui.Input{}, ui.Rect{ width: 4, height: 4 })
  ui.label(&context, ui.Rect{ x: 1, y: 1, width: 2, height: 2 }, "A", ui.Color{ a: 255 })
  ui.end(&context)
  check(software.render(&surface, ui.first(&context), font).ok)
  check(bytes[27] == 128 && bytes[47] == 255 && bytes[23] == 0)
  trace = Trace{}
  ui.begin(&context, arena, ui.Input{}, ui.Rect{ width: 4, height: 4 })
  ui.label(&context, ui.Rect{ width: 4, height: 4 }, "\xff\xc3\xa9", ui.Color{ a: 255 })
  ui.end(&context)
  check(software.render(&surface, ui.first(&context), font).ok)
  check(trace.calls == 2 && trace.first == 65533 && trace.last == 233)
  trace.invalid = true
  check(software.render(&surface, ui.first(&context), font).kind == errors.Kind.InvalidInput)
  surface.stride = 15
  check(software.render(&surface, ui.first(&context), font).kind == errors.Kind.InvalidInput)
  surface.stride = 20
  check(software.render(&surface, ui.first(&context), software.Font{}).kind == errors.Kind.InvalidInput)
}
fn main() {
  arena := mem.Arena{}
  defer { mem.arena_release(&arena) }
  interactions(&arena)
  widgets(&arena)
  raster(&arena)
  huge := ui.Rect{ x: 2147483640, y: 2147483640, width: 2147483647, height: 2147483647 }
  check(ui.contains(huge, 2147483647, 2147483647))
  overlap := ui.intersect(huge, ui.Rect{ x: 2147483647, y: 2147483647, width: 10, height: 10 })
  check(overlap.width == 10 && overlap.height == 10)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-ui-results-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE)
    for mode in ('--debug', '--release'):
        output = work / 'program'
        subprocess.run([DYN, 'build', str(work), mode, '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=300)
        subprocess.run([str(output)], check=True, timeout=30)
    for target in ('aarch64-linux', 'riscv64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows', 'wasm32-wasi'):
        output = work / target
        subprocess.run([DYN, 'build', str(work), '--release', '--opt-level', '3', '--target', target, '--quiet', '--output', str(output)], check=True, timeout=300)
        emulator = {'aarch64-linux': 'qemu-aarch64', 'riscv64-linux': 'qemu-riscv64', 'x86_64-windows': 'wine'}.get(target)
        if emulator and shutil.which(emulator):
            subprocess.run([emulator, str(output)], check=True, timeout=60)
        if target == 'wasm32-wasi' and shutil.which('node'):
            script = "const {WASI}=require('node:wasi'),fs=require('node:fs');(async()=>{const wasi=new WASI({version:'preview1',returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});"
            subprocess.run(['node', '--no-warnings', '-e', script, str(output)], check=True, timeout=60)
    reference = None
    for mode in ('--debug', '--release'):
        output = work / 'demo'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/ui-demo'), mode, '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=300)
        subprocess.run([str(output)], cwd=work, check=True, timeout=30)
        image = (work / 'ui-demo.png').read_bytes()
        assert image[:8] == b'\x89PNG\r\n\x1a\n' and int.from_bytes(image[16:20], 'big') == 480 and int.from_bytes(image[20:24], 'big') == 240
        if reference is not None:
            assert image == reference, 'debug/release UI pixels differ'
        reference = image
    failures = {
        'UI frame not begun': 'ui.end(&context)',
        'UI frame already begun': 'ui.begin(&context, &arena, ui.Input{}, bounds)\n ui.begin(&context, &arena, ui.Input{}, bounds)',
        'UI frame not ended': 'ui.begin(&context, &arena, ui.Input{}, bounds)\n _ = ui.first(&context)',
        'UI widget ID must be nonzero': 'ui.begin(&context, &arena, ui.Input{}, bounds)\n _ = ui.button(&context, 0, bounds, "", true)',
    }
    for message, body in failures.items():
        (work / 'main.dyn').write_text('use "std/ui" ui\nuse "std/mem" mem\nfn main() {\n arena := mem.Arena{}\n context := ui.Context{}\n bounds := ui.Rect{ width: 10, height: 10 }\n '+body+'\n}')
        for mode in ('--debug', '--release'):
            output = work / 'invalid'
            subprocess.run([DYN, 'build', str(work), mode, '--quiet', '--output', str(output)], check=True, timeout=300)
            ran = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
            assert ran.returncode != 0 and message in ran.stderr, (message, ran.stderr)
print('PASS UI: interaction, capture, focus, widgets, clipping, owned text, RGBA blending, glyph coverage, UTF-8, errors and cross-targets')
