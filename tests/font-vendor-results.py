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
empty_face: rawptr
empty_face_destroyed: u32
blob_destroyed: u32
real_blob_destroy: fn(rawptr)
fn empty_face_create(blob: rawptr, index: u32) rawptr { _ = blob
 _ = index
 return empty_face }
fn count_empty_face_destroy(face: rawptr) { check(face == empty_face)
 empty_face_destroyed += 1 }
fn count_blob_destroy(blob: rawptr) { blob_destroyed += 1
 real_blob_destroy(blob) }
fn reject_empty_glyph_count(face: rawptr) u32 { _ = face
 #panic("empty face must not be validated as malformed font") }
empty_font: rawptr
empty_destroyed: u32
fn empty_create(face: rawptr) rawptr { _ = face
 return empty_font }
fn count_empty_destroy(font: rawptr) { check(font == empty_font)
 empty_destroyed += 1 }
fn reject_empty_configuration(font: rawptr) { _ = font
 #panic("empty font must not be configured") }
fn main(){
 arena := mem.arena_create(0)
 defer {mem.arena_release(arena)}
 library := dynlib.open("FT_LIBRARY",dynlib.Now)
 check(library.ok)
 defer {_ = dynlib.close(&library.value)}
 ft_loaded := ft.load(library.value)
 check(ft_loaded.ok && !ft.load(nil).ok)
 font_bytes := fs.read_all(arena,"font.ttf",10000000)
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
 output := mem.push_array(u8,arena,24+#cast(usize,value.width)*#cast(usize,value.height))
 fields: [6]u32 = [#cast(u32,value.width),#cast(u32,value.height),#cast(u32,value.left),#cast(u32,value.top),#cast(u32,value.advance_x),#cast(u32,value.advance_y)]
 for i in 0..6 {binary.store_u32_le(output[i*4..i*4+4],fields[i])}
 for row in 0..value.height {for x in 0..value.width {output[24+#cast(usize,row*value.width+x)] = value.pixels[#cast(usize,row)*value.stride+#cast(usize,x)]}}
 check(fs.write_all("ft-actual.bin",output).ok)
 metrics:=ft.face_metrics(font.face)
 check(metrics.ok && ft.face_metrics(nil).kind==errors.Kind.InvalidInput)
 values:=metrics.value
 metric_fields:[7]u32=[#cast(u32,values.units_per_em),#cast(u32,#cast(i32,values.ascent)),#cast(u32,#cast(i32,values.descent)),#cast(u32,#cast(i32,values.height)),values.glyph_count,values.face_count,values.face_index]
 metric_bytes:[28]u8=[]
 for i in 0..7 {binary.store_u32_le(metric_bytes[i*4..i*4+4],metric_fields[i])}
 check(fs.write_all("metrics-actual.bin",metric_bytes[..]).ok)
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
 empty_face = loaded.api.face_get_empty()
 real_blob_destroy = loaded.api.blob_destroy
 face_oom := loaded.api
 face_oom.face_create = empty_face_create
 face_oom.face_destroy = count_empty_face_destroy
 face_oom.blob_destroy = count_blob_destroy
 face_oom.face_glyph_count = reject_empty_glyph_count
 failed_face := hb.font_owned(&face_oom,font_bytes.value,0)
 check(!failed_face.ok && failed_face.kind == errors.Kind.System && failed_face.value == nil && empty_face_destroyed == 1 && blob_destroyed == 1)
 defer {loaded.api.font_destroy(created.value)}
 loaded.api.font_set_scale(created.value,2048,2048)
 features: []const hb.Feature
 latin := hb.shape(arena,&loaded.api,created.value,"office AV",0,features)
 arabic := hb.shape(arena,&loaded.api,created.value,"السلام",0,features)
 check(latin.ok && #len(latin.value) < 9 && arabic.ok && #len(arabic.value) <= 6)
 check(arabic.value[0].cluster > arabic.value[#len(arabic.value)-1].cluster)
 for glyph in latin.value {check(glyph.index != 0)}
 for glyph in arabic.value {check(glyph.index != 0)}
 save(arena,latin.value,"latin-actual.bin")
 save(arena,arabic.value,"arabic-actual.bin")
 run := hb.shape_run(arena,&loaded.api,created.value,"السَلام",hb.Options{direction:hb.RightToLeft,script:1098015074,language:"ar",cluster_level:hb.MonotoneCharacters,flags:hb.BeginningOfText|hb.EndOfText},features)
 check(run.ok)
 save(arena,run.value,"run-actual.bin")
 context_run:=hb.shape_run(arena,&loaded.api,created.value,"بجح",hb.Options{direction:hb.RightToLeft,script:1098015074,language:"ar",cluster_level:1,item_offset:2,item_length:2},features)
 check(context_run.ok && #len(context_run.value)>0 && context_run.value[0].cluster==2)
 save(arena,context_run.value,"context-actual.bin")
 unicode := loaded.api.unicode_get_default()
 check(unicode!=nil && loaded.api.unicode_script(unicode,65)==1281455214 && loaded.api.script_horizontal_direction(1098015074)==hb.RightToLeft)
 checkpoint := mem.arena_mark(arena)
 check(hb.shape_run(arena,&loaded.api,created.value,"x",hb.Options{cluster_level:3},features).kind==errors.Kind.InvalidInput)
 check(hb.shape_run(arena,&loaded.api,created.value,"x",hb.Options{flags:256},features).kind==errors.Kind.InvalidInput)
 check(hb.shape_run(arena,&loaded.api,created.value,"x",hb.Options{language:"a\0r"},features).kind==errors.Kind.InvalidInput)
 check(hb.shape_run(arena,&loaded.api,created.value,"x",hb.Options{item_offset:2},features).kind==errors.Kind.InvalidInput)
 check(hb.shape_run(arena,&loaded.api,created.value,"x",hb.Options{item_length:2},features).kind==errors.Kind.InvalidInput)
 check(hb.shape_run(arena,&loaded.api,created.value,"x",hb.Options{item_length: -2},features).kind==errors.Kind.InvalidInput)
 check(mem.arena_mark(arena)==checkpoint)
 // The FreeType callback consumes shaped glyph IDs with baseline origins.
 adapter := ft.Adapter{font:&font,line_height:40,glyph_ids:true}
 context := ui.Context{}
 viewport := ui.Rect{width:256,height:64}
 ui.begin(&context,arena,ui.Input{},viewport)
 pen: i64 = 20*64
 for glyph in arabic.value {ui.glyph(&context,viewport,glyph.index,(pen+#cast(i64,glyph.x_offset))/64,40-#cast(i64,glyph.y_offset)/64,ui.Color{r:255,g:255,b:255,a:255})
 pen += #cast(i64,glyph.x_advance)}
 ui.end(&context)
 pixels := mem.push_array(u8,arena,#cast(usize,256*64*4))
 surface := software.Surface{pixels:pixels,width:256,height:64,stride:256*4}
 check(software.render(&surface,ui.first(&context),ft.renderer(&adapter)).ok)
 ink: usize = 0
 for pixel in pixels {if pixel != 0 {ink += 1}}
 check(ink > 100 && adapter.kind == errors.Kind.None)
 bad := ft.Font{}
 check(!ft.open(&bad,ft_loaded.api,"broken",0,32).ok && bad.face == nil && bad.library == nil)
 check(hb.font_owned(&loaded.api,"broken",0).kind == errors.Kind.InvalidInput)
 check(hb.shape(arena,&loaded.api,created.value,"x",1,features).kind == errors.Kind.InvalidInput)
 ft.close(&font)
 ft.close(&font)
}
'''
font=next((p for p in (Path('/usr/share/fonts/TTF/DejaVuSans.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')) if p.exists()),None)
ft=ctypes.util.find_library('freetype');hb=ctypes.util.find_library('harfbuzz')
if not font or not ft or not hb or not shutil.which('pkg-config') or subprocess.run(['pkg-config','--exists','freetype2','harfbuzz']).returncode:
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
        for item in ('ft','metrics','latin','arabic','run','context'):
            assert (work/(item+'-actual.bin')).read_bytes()==(work/(item+'-reference.bin')).read_bytes(),item
    for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows'):
        subprocess.run([DYN,'build',str(work),'--target',target,'--release','--quiet','--no-link','--emit-object','--output',str(work/target)],check=True,timeout=300)
print('PASS FreeType/HarfBuzz: native C ABI/raster oracle, Latin ligature/kerning and Arabic shaping, borrowed bitmap UI adapter, malformed fonts, ownership; debug/O2/O3 + six cross-objects')
