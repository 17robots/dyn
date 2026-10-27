#!/usr/bin/env python3
"""Dynamic FreeType/HarfBuzz against native C ABI, shaping and raster oracles."""
import ctypes.util
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use "vendor/freetype" ft
use "vendor/harfbuzz" hb
use "std/dynlib" dynlib
use "std/fs" fs
use "std/mem" mem
use "std/encoding/binary" binary
use "std/ui" ui
use "std/ui/software" software
use "std/errors" errors
fn check(ok: bool){if !ok {#panic("font vendor contract")}}
fn save(arena: *mem.Arena, glyphs: []const hb.Glyph, path: []const u8){
 output := mem.push_array(u8,arena,4+#len(glyphs)*24)
 binary.store_u32_le(output[..4],#cast(u32,#len(glyphs)))
 for i in 0..#len(glyphs){glyph := glyphs[i]
 values: [6]u32 = [glyph.index,glyph.cluster,#cast(u32,glyph.x_advance),#cast(u32,glyph.y_advance),#cast(u32,glyph.x_offset),#cast(u32,glyph.y_offset)]
 for j in 0..6 {binary.store_u32_le(output[4+i*24+j*4..8+i*24+j*4],values[j])}}
 check(fs.write_all(path,output).ok)
}
empty_font: rawptr
empty_destroyed: u32
fn empty_create(face: rawptr) rawptr { _ = face
 return empty_font }
fn count_empty_destroy(font: rawptr) { check(font == empty_font)
 empty_destroyed += 1 }
fn reject_empty_configuration(font: rawptr) { _ = font
 #panic("empty font must not be configured") }
fn main(){
 arena := mem.Arena{}
 defer {mem.arena_release(&arena)}
 library := dynlib.open("FT_LIBRARY",dynlib.Now)
 check(library.ok)
 defer {_ = dynlib.close(&library.value)}
 ft_loaded := ft.load(library.value)
 check(ft_loaded.ok && !ft.load(nil).ok)
 font_bytes := fs.read_all(&arena,"font.ttf",10000000)
 check(font_bytes.ok)
 font := ft.Font{}
 check(ft.open(&font,ft_loaded.api,font_bytes.value,0,32).ok)
 defer {ft.close(&font)}
 check(ft.open(&font,ft_loaded.api,font_bytes.value,0,32).kind == errors.Kind.InvalidState)
 index := ft_loaded.api.char_index(font.face,65)
 check(index != 0 && ft_loaded.api.load_glyph(font.face,index,ft.LoadRender) == 0)
 bitmap := ft.bitmap(font.face)
 check(bitmap.ok && bitmap.value.width > 0 && bitmap.value.height > 0)
 value := bitmap.value
 output := mem.push_array(u8,&arena,24+#cast(usize,value.width)*#cast(usize,value.height))
 fields: [6]u32 = [#cast(u32,value.width),#cast(u32,value.height),#cast(u32,value.left),#cast(u32,value.top),#cast(u32,value.advance_x),#cast(u32,value.advance_y)]
 for i in 0..6 {binary.store_u32_le(output[i*4..i*4+4],fields[i])}
 for row in 0..value.height {for x in 0..value.width {output[24+#cast(usize,row*value.width+x)] = value.pixels[#cast(usize,row)*value.stride+#cast(usize,x)]}}
 check(fs.write_all("ft-actual.bin",output).ok)
 shaping := dynlib.open("HB_LIBRARY",dynlib.Now)
 check(shaping.ok)
 defer {_ = dynlib.close(&shaping.value)}
 loaded := hb.load(shaping.value)
 check(loaded.ok && !hb.load(nil).ok)
 created := hb.font_owned(&loaded.api,font_bytes.value,0)
 check(created.ok)
 empty_font = loaded.api.font_get_empty()
 oom_api := loaded.api
 oom_api.font_create = empty_create
 oom_api.font_destroy = count_empty_destroy
 oom_api.ot_font_set_funcs = reject_empty_configuration
 failed_font := hb.font_owned(&oom_api,font_bytes.value,0)
 check(!failed_font.ok && failed_font.kind == errors.Kind.System && failed_font.value == nil && empty_destroyed == 1)
 defer {loaded.api.font_destroy(created.value)}
 loaded.api.font_set_scale(created.value,2048,2048)
 features: []const hb.Feature
 latin := hb.shape(&arena,&loaded.api,created.value,"office AV",0,features)
 arabic := hb.shape(&arena,&loaded.api,created.value,"السلام",0,features)
 check(latin.ok && #len(latin.value) < 9 && arabic.ok && #len(arabic.value) <= 6)
 check(arabic.value[0].cluster > arabic.value[#len(arabic.value)-1].cluster)
 for glyph in latin.value {check(glyph.index != 0)}
 for glyph in arabic.value {check(glyph.index != 0)}
 save(&arena,latin.value,"latin-actual.bin")
 save(&arena,arabic.value,"arabic-actual.bin")
 // The FreeType callback consumes shaped glyph IDs with baseline origins.
 adapter := ft.Adapter{font:&font,line_height:40,glyph_ids:true}
 context := ui.Context{}
 viewport := ui.Rect{width:256,height:64}
 ui.begin(&context,&arena,ui.Input{},viewport)
 pen: i64 = 20*64
 for glyph in arabic.value {ui.glyph(&context,viewport,glyph.index,(pen+#cast(i64,glyph.x_offset))/64,40-#cast(i64,glyph.y_offset)/64,ui.Color{r:255,g:255,b:255,a:255})
 pen += #cast(i64,glyph.x_advance)}
 ui.end(&context)
 pixels := mem.push_array(u8,&arena,#cast(usize,256*64*4))
 surface := software.Surface{pixels:pixels,width:256,height:64,stride:256*4}
 check(software.render(&surface,ui.first(&context),ft.renderer(&adapter)).ok)
 ink: usize = 0
 for pixel in pixels {if pixel != 0 {ink += 1}}
 check(ink > 100 && adapter.kind == errors.Kind.None)
 bad := ft.Font{}
 check(!ft.open(&bad,ft_loaded.api,"broken",0,32).ok && bad.face == nil && bad.library == nil)
 check(!hb.font_owned(&loaded.api,"broken",0).ok)
 check(hb.shape(&arena,&loaded.api,created.value,"x",1,features).kind == errors.Kind.InvalidInput)
 ft.close(&font)
 ft.close(&font)
}
'''
font=next((p for p in (Path('/usr/share/fonts/TTF/DejaVuSans.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')) if p.exists()),None)
ft=ctypes.util.find_library('freetype');hb=ctypes.util.find_library('harfbuzz')
if not font or not ft or not hb or not shutil.which('pkg-config'):
    print('SKIP font vendor native oracle: FreeType/HarfBuzz development packages and DejaVu Sans required');raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-font-vendors-') as directory:
    work=Path(directory);shutil.copy(font,work/'font.ttf')
    (work/'main.dyn').write_text(SOURCE.replace('FT_LIBRARY',ft).replace('HB_LIBRARY',hb))
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','freetype2','harfbuzz'],text=True))
    oracle=work/'reference'
    subprocess.run([*shlex.split(os.environ.get('CC','cc')),str(ROOT/'tests/font-vendor-results.c'),*flags,'-o',str(oracle)],check=True,timeout=60)
    subprocess.run([str(oracle)],cwd=work,check=True,timeout=60)
    for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
        output=work/'program'
        subprocess.run([DYN,'build',str(work),*flags,'--quiet','--no-cache','--output',str(output)],check=True,timeout=300)
        subprocess.run([str(output)],cwd=work,check=True,timeout=60)
        for item in ('ft','latin','arabic'):
            assert (work/(item+'-actual.bin')).read_bytes()==(work/(item+'-reference.bin')).read_bytes(),item
    for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows'):
        subprocess.run([DYN,'build',str(work),'--target',target,'--release','--quiet','--no-link','--emit-object','--output',str(work/target)],check=True,timeout=300)
print('PASS FreeType/HarfBuzz: native C ABI/raster oracle, Latin ligature/kerning and Arabic shaping, borrowed bitmap UI adapter, malformed fonts, ownership; debug/O2/O3 + six cross-objects')
