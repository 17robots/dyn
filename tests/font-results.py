#!/usr/bin/env python3
"""Synthetic TrueType outlines and independent coverage/metadata oracles."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import private_display  # hides the desktop display; see tests/private_display.py

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
u16 = lambda n: struct.pack('>H', n)
i16 = lambda n: struct.pack('>h', n)
u32 = lambda n: struct.pack('>I', n)

def simple(points, ends):
    header = i16(len(ends)) + b''.join(i16(n) for n in (0, 0, 1000, 1000))
    flags = bytes(1 if point[2] else 0 for point in points)
    deltas = b''
    for axis in range(2):
        previous = 0
        for point in points:
            deltas += i16(point[axis] - previous)
            previous = point[axis]
    data = header + b''.join(u16(n) for n in ends) + u16(0) + flags + deltas
    return data + b'\0' * (len(data) % 2)

square = [(0,0,True),(1000,0,True),(1000,1000,True),(0,1000,True)]
inner = [(250,250,True),(250,750,True),(750,750,True),(750,250,True)]
glyphs = [b'', simple(square,[3]), simple(square+inner,[3,7]), simple([(0,0,True),(500,1000,False),(1000,0,True)],[2]), i16(-1)+b'\0'*8]

def fixture(long_loca=False, cmap12=False):
    head = bytearray(54); head[12:16] = u32(0x5f0f3cf5); head[18:20] = u16(1000); head[50:52] = i16(int(long_loca))
    hhea = bytearray(36); hhea[4:10] = i16(1000)+i16(-200)+i16(0); hhea[34:36] = u16(2)
    offsets=[0]
    for glyph in glyphs: offsets.append(offsets[-1]+len(glyph))
    loca = b''.join(u32(n) if long_loca else u16(n//2) for n in offsets)
    if cmap12:
        sub = u16(12)+u16(0)+u32(28)+u32(0)+u32(1)+u32(65)+u32(68)+u32(1)
    else:
        sub = u16(4)+u16(32)+u16(0)+u16(4)+u16(4)+u16(1)+u16(0)+u16(68)+u16(65535)+u16(0)+u16(65)+u16(65535)+u16((-64)&65535)+u16(1)+u16(0)+u16(0)
    cmap = u16(0)+u16(1)+u16(3)+u16(10 if cmap12 else 1)+u32(12)+sub
    tables = {'head':bytes(head),'hhea':bytes(hhea),'maxp':u32(0x10000)+u16(5), 'hmtx':u16(1000)+i16(0)+u16(700)+i16(0)+i16(0)*3,'loca':loca,'glyf':b''.join(glyphs),'cmap':cmap}
    offset=12+16*len(tables); directory=b''; body=b''; positions={}
    for tag,data in tables.items():
        positions[tag]=offset
        directory += tag.encode()+u32(0)+u32(offset)+u32(len(data))
        body += data; offset += len(data)
    return u32(0x10000)+u16(len(tables))+b'\0'*6+directory+body,positions

SOURCE = r'''use font "std/font"
use font_ui "std/font/ui"
use ui "std/ui"
use software "std/ui/software"
use mem "std/mem"
use parse "std/parse"
fn check(ok: bool) { if !ok { #panic("font contract") } }
fn opens(bytes: []const u8) bool {
  _ = font.open(bytes) catch { return false }
  return true
}
// Whether rastering fails with an Invalid parse error.
fn raster_invalid(arena: *mem.Arena, face: *const font.Face, glyph: u16, size: u16) bool {
  _ = font.raster(arena, face, glyph, size) catch err {
    case err {
      .Invalid => { return true }
      _ => { return false }
    }
  }
  return false
}
// Rasters glyph; a failure must leave the arena where it was.
fn raster_rewinds(arena: *mem.Arena, face: *const font.Face, glyph: u16) bool {
  before := mem.arena_mark(arena)
  _ = font.raster(arena, face, glyph, 16) catch { return mem.arena_mark(arena) == before }
  return true
}
fn atlas_too_small(arena: *mem.Arena, face: *const font.Face, codepoints: []const u32) bool {
  _ = font.atlas(arena, face, codepoints, 16, 1, 1) catch err {
    case err {
      .TooLarge => { return true }
      _ => { return false }
    }
  }
  return false
}
fn adapter_invalid(err: parse.ParseErr) bool {
  case err {
    .Invalid => { return true }
    _ => { return false }
  }
}
fn renders(surface: *software.Surface, commands: *const ui.Command, glyphs: software.Font) bool {
  software.render(surface, commands, glyphs) catch { return false }
  return true
}
fn main() {
  arena := mem.arena_alloc(0)
  frame := mem.arena_alloc(0)
  defer { mem.arena_release(frame)
    mem.arena_release(arena) }
  face := font.open(data[..]) catch { #panic("unexpected failure") }
  check(font.glyph_index(&face, 65) == 1 && font.glyph_index(&face, 68) == 4 && font.glyph_index(&face, 69) == 0)
  check(font.glyph_index(&face, 0xd800) == 0 && font.glyph_index(&face, 0x110000) == 0)
  for length in 0..data.len { check(!opens(data[..length])) }
  solid := font.raster(arena, &face, 1, 16) catch { #panic("unexpected failure") }
  check(solid.width == 16 && solid.height == 16 && solid.y_offset == -16 && solid.advance == 11)
  for pixel in solid.pixels { check(pixel == 255) }
  hole := font.raster(arena, &face, 2, 16) catch { #panic("unexpected failure") }
  for y in 0..16 { for x in 0..16 {
    expected: u8 = 255
    if x >= 4 && x < 12 && y >= 4 && y < 12 { expected = 0 }
    check(hole.pixels[y * 16 + x] == expected)
  } }
  curve := font.raster(arena, &face, 3, 16) catch { #panic("unexpected failure") }
  // Analytic quadratic parabola, independent of the edge flattener.
  partial := false
  for y in 0..16 { for x in 0..16 {
    hits: i32 = 0
    for sy in 0..4 { for sx in 0..4 {
      t := (#cast(f64, x) + (#cast(f64, sx) + 0.5) / 4.0) / 16.0
      py := #cast(f64, y) + (#cast(f64, sy) + 0.5) / 4.0
      if py >= 16.0 - 32.0 * t * (1.0 - t) { hits += 1 }
    } }
    expected := (hits * 255 + 8) / 16
    actual := #cast(i32, curve.pixels[y * 16 + x])
    check(actual - expected <= 32 && expected - actual <= 32)
    if actual > 0 && actual < 255 { partial = true }
  } }
  check(partial)
  _ = font.raster(arena, &face, 0, 16) catch { #panic("unexpected failure") }
  mark := mem.arena_mark(arena)
  check(raster_invalid(arena, &face, 4, 16))
  check(raster_invalid(arena, &face, 5, 16))
  check(raster_invalid(arena, &face, 1, 0))
  check(mem.arena_mark(arena) == mark)
  // Corrupt every byte through deterministic mutations; valid parses must also
  // survive bounded rasterization without a language bounds/overflow trap.
  work := data
  for iteration in 0..2000 {
    index := (iteration * 37) % work.len
    work[index] ^= #cast(u8, (1 << (iteration % 8)))
    if opens(work[..]) {
      parsed := font.open(work[..]) catch { #panic("open") }
      for glyph in 0..5 {
        check(raster_rewinds(arena, &parsed, #cast(u16, glyph)))
        mem.arena_rewind(arena, mark)
      }
    }
    work[index] = data[index]
  }
  codepoints: [3]u32 = [65, 66, 67]
  cached := font.atlas(arena, &face, codepoints[..], 16, 64, 16) catch { #panic("unexpected failure") }
  check(cached.line_height == 20)
  check(font.atlas_glyph(&cached, 65).advance == 11)
  check(font.atlas_glyph(&cached, 999).advance == 16)
  before := mem.arena_mark(arena)
  check(atlas_too_small(arena, &face, codepoints[..]))
  check(mem.arena_mark(arena) == before)
  context := ui.Context{ style: ui.default_style }
  ui.begin(&context, frame, ui.Input{}, ui.Rect{ width: 64, height: 32 })
  ui.label(&context, ui.Rect{ width: 64, height: 32 }, "ABC", ui.Color{ r: 200, a: 255 })
  ui.end(&context)
  pixels: [8192]u8
  surface := software.Surface{ pixels: pixels[..], width: 64, height: 32, stride: 256 }
  adapter := font_ui.Adapter{ face: &face, arena: arena, pixels_per_em: 16 }
  check(renders(&surface, ui.first(&context), font_ui.renderer(&adapter)) && !adapter.failed && pixels[3] == 255)
  expected := pixels
  for i in 0..pixels.len { pixels[i] = 0 }
  before = mem.arena_mark(arena)
  check(renders(&surface, ui.first(&context), font_ui.atlas_renderer(&cached)))
  check(mem.arena_mark(arena) == before)
  for i in 0..pixels.len { check(pixels[i] == expected[i]) }
  ui.begin(&context, frame, ui.Input{}, ui.Rect{ width: 64, height: 32 })
  ui.label(&context, ui.Rect{ width: 64, height: 32 }, "D", ui.Color{ a: 255 })
  ui.end(&context)
  check(!renders(&surface, ui.first(&context), font_ui.renderer(&adapter)) && adapter.failed && adapter_invalid(adapter.failure))
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-font-results-') as directory:
    work=Path(directory)
    for long_loca,cmap12 in ((False,False),(True,True)):
        data,positions=fixture(long_loca,cmap12)
        declaration='data: ['+str(len(data))+']u8 = ['+','.join(map(str,data))+']\n'
        (work/'main.dyn').write_text(declaration+SOURCE)
        for mode in ('--debug','--release'):
            output=work/'program'
            subprocess.run([DYN,'build',str(work),mode,'--quiet','--no-cache','--output',str(output)],check=True,timeout=300)
            subprocess.run([str(output)],check=True,timeout=90)
    # Exercise the same fixture and UI bridge on independent native backends.
    for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows','wasm32-wasi'):
        output=work/target
        subprocess.run([DYN,'build',str(work),'--release','--target',target,'--quiet','--output',str(output)],check=True,timeout=300)
        emulator={'aarch64-linux':'qemu-aarch64','riscv64-linux':'qemu-riscv64','x86_64-windows':'wine'}.get(target)
        if emulator and shutil.which(emulator): subprocess.run([emulator,str(output)],check=True,timeout=120)
        if target == 'wasm32-wasi' and shutil.which('node'):
            script = "const {WASI}=require('node:wasi'),fs=require('node:fs');(async()=>{const wasi=new WASI({version:'preview1',returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});"
            subprocess.run(['node','--no-warnings','-e',script,str(output)],check=True,timeout=120)
    # The example takes font/output paths; no font data is copied into the repo.
    system_font = Path('/usr/share/fonts/liberation/LiberationSans-Regular.ttf')
    if system_font.is_file():
        reference = None
        for mode in ('--debug', '--release'):
            output = work / 'font-demo'
            subprocess.run([DYN, 'build', str(ROOT / 'tests/font-ui-demo'), mode, '--quiet', '--output', str(output)], check=True, timeout=300)
            image = work / 'font-demo.png'
            subprocess.run([str(output), str(system_font), str(image)], check=True, timeout=120)
            encoded = image.read_bytes()
            assert encoded[:8] == b'\x89PNG\r\n\x1a\n'
            if reference is not None:
                assert encoded == reference, 'font demo differs in debug/release'
            reference = encoded
    else:
        print('SKIP optional system-font PNG demo: Liberation Sans unavailable')
print('PASS font: cmap 4/12, loca variants, outlines, holes, quadratic coverage, truncation/mutation safety, rollback, UI adapter and cross-targets')
