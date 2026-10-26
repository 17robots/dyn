#!/usr/bin/env python3
"""Synthetic TrueType outlines and independent coverage/metadata oracles."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

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

SOURCE = r'''use "std/font" font
use "std/font/ui" font_ui
use "std/ui" ui
use "std/ui/software" software
use "std/mem" mem
use "std/errors" errors
fn check(ok: bool) { if !ok { #panic("font contract") } }
fn main() {
  arena := mem.Arena{}
  frame := mem.Arena{}
  defer { mem.arena_release(&frame)
    mem.arena_release(&arena) }
  opened := font.open(data[..])
  check(opened.ok)
  face := opened.value
  check(font.glyph_index(&face, 65) == 1 && font.glyph_index(&face, 68) == 4 && font.glyph_index(&face, 69) == 0)
  check(font.glyph_index(&face, 0xd800) == 0 && font.glyph_index(&face, 0x110000) == 0)
  for length in 0..#len(data) { check(!font.open(data[..length]).ok) }
  solid := font.raster(&arena, &face, 1, 16)
  check(solid.ok && solid.value.width == 16 && solid.value.height == 16 && solid.value.y_offset == -16 && solid.value.advance == 11)
  for pixel in solid.value.pixels { check(pixel == 255) }
  hole := font.raster(&arena, &face, 2, 16)
  check(hole.ok)
  for y in 0..16 { for x in 0..16 {
    expected: u8 = 255
    if x >= 4 && x < 12 && y >= 4 && y < 12 { expected = 0 }
    check(hole.value.pixels[y * 16 + x] == expected)
  } }
  curve := font.raster(&arena, &face, 3, 16)
  check(curve.ok)
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
    actual := #cast(i32, curve.value.pixels[y * 16 + x])
    check(actual - expected <= 32 && expected - actual <= 32)
    if actual > 0 && actual < 255 { partial = true }
  } }
  check(partial)
  check(font.raster(&arena, &face, 0, 16).ok)
  mark := mem.arena_mark(&arena)
  check(font.raster(&arena, &face, 4, 16).kind == errors.Kind.Unsupported)
  check(font.raster(&arena, &face, 5, 16).kind == errors.Kind.InvalidInput)
  check(font.raster(&arena, &face, 1, 0).kind == errors.Kind.InvalidInput)
  check(mem.arena_mark(&arena) == mark)
  // Corrupt every byte through deterministic mutations; valid parses must also
  // survive bounded rasterization without a language bounds/overflow trap.
  work := data
  for iteration in 0..2000 {
    index := (iteration * 37) % #len(work)
    work[index] ^= #cast(u8, (1 << (iteration % 8)))
    parsed := font.open(work[..])
    if parsed.ok {
      for glyph in 0..5 {
        before := mem.arena_mark(&arena)
        result := font.raster(&arena, &parsed.value, #cast(u16, glyph), 16)
        if !result.ok { check(mem.arena_mark(&arena) == before) }
        mem.arena_rewind(&arena, mark)
      }
    }
    work[index] = data[index]
  }
  codepoints: [3]u32 = [65, 66, 67]
  cached := font.atlas(&arena, &face, codepoints[..], 16, 64, 16)
  check(cached.ok && cached.value.line_height == 20)
  check(font.atlas_glyph(&cached.value, 65).advance == 11)
  check(font.atlas_glyph(&cached.value, 999).advance == 16)
  before := mem.arena_mark(&arena)
  check(font.atlas(&arena, &face, codepoints[..], 16, 1, 1).kind == errors.Kind.Capacity)
  check(mem.arena_mark(&arena) == before)
  context := ui.Context{}
  ui.begin(&context, &frame, ui.Input{}, ui.Rect{ width: 64, height: 32 })
  ui.label(&context, ui.Rect{ width: 64, height: 32 }, "ABC", ui.Color{ r: 200, a: 255 })
  ui.end(&context)
  pixels: [8192]u8 = []
  surface := software.Surface{ pixels: pixels[..], width: 64, height: 32, stride: 256 }
  adapter := font_ui.Adapter{ face: &face, arena: &arena, pixels_per_em: 16 }
  result := software.render(&surface, ui.first(&context), font_ui.renderer(&adapter))
  check(result.ok && !adapter.failed && pixels[3] == 255)
  expected := pixels
  for i in 0..#len(pixels) { pixels[i] = 0 }
  before = mem.arena_mark(&arena)
  check(software.render(&surface, ui.first(&context), font_ui.atlas_renderer(&cached.value)).ok)
  check(mem.arena_mark(&arena) == before)
  for i in 0..#len(pixels) { check(pixels[i] == expected[i]) }
  ui.begin(&context, &frame, ui.Input{}, ui.Rect{ width: 64, height: 32 })
  ui.label(&context, ui.Rect{ width: 64, height: 32 }, "D", ui.Color{ a: 255 })
  ui.end(&context)
  result = software.render(&surface, ui.first(&context), font_ui.renderer(&adapter))
  check(!result.ok && adapter.failed && adapter.kind == errors.Kind.Unsupported)
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
