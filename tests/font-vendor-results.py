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
SOURCE=r'''use ft "vendor/freetype"
use hb "vendor/harfbuzz"
use dynlib "std/dynlib"
use "std/fail"
use fs "std/fs"
use mem "std/mem"
use binary "std/encoding/binary"
use ui "std/ui"
use software "std/ui/software"
use errors "std/io"
struct ft_face_metrics_Outcome { value: ft.FaceMetrics, failure: fail.Failure, kind: fail.Kind }
fn ft_face_metrics(p0: rawptr) ft_face_metrics_Outcome {
  status: fail.Status
  value := ft.face_metrics(&status, p0)
  return ft_face_metrics_Outcome{ value: value, failure: status.failure, kind: status.failure.kind }
}

struct ft_bitmap_Outcome { value: ft.BitmapView, failure: fail.Failure, kind: fail.Kind }
fn ft_bitmap(p0: rawptr) ft_bitmap_Outcome {
  status: fail.Status
  value := ft.bitmap(&status, p0)
  return ft_bitmap_Outcome{ value: value, failure: status.failure, kind: status.failure.kind }
}

struct ft_open_Outcome { failure: fail.Failure, kind: fail.Kind }
fn ft_open(p0: *ft.Font, p1: ft.Api, p2: []const u8, p3: u32, p4: u32) ft_open_Outcome {
  status: fail.Status
  ft.open(&status, p0, p1, p2, p3, p4)
  return ft_open_Outcome{ failure: status.failure, kind: status.failure.kind }
}

struct ft_load_Outcome { api: ft.Api, failure: fail.Failure, kind: fail.Kind }
fn ft_load(p0: dynlib.Handle) ft_load_Outcome {
  status: fail.Status
  value := ft.load(&status, p0)
  return ft_load_Outcome{ api: value, failure: status.failure, kind: status.failure.kind }
}

struct hb_font_owned_Outcome { value: rawptr, failure: fail.Failure, kind: fail.Kind }
fn hb_font_owned(p0: *const hb.Api, p1: []const u8, p2: u32) hb_font_owned_Outcome {
  status: fail.Status
  value := hb.font_owned(&status, p0, p1, p2)
  return hb_font_owned_Outcome{ value: value, failure: status.failure, kind: status.failure.kind }
}

struct hb_shape_Outcome { value: []hb.Glyph, failure: fail.Failure, kind: fail.Kind }
fn hb_shape(a0: *mem.Arena, p0: *const hb.Api, p1: rawptr, p2: []const u8, p3: u32, p4: []const hb.Feature) hb_shape_Outcome {
  status: fail.Status
  value := hb.shape(a0, &status, p0, p1, p2, p3, p4)
  return hb_shape_Outcome{ value: value, failure: status.failure, kind: status.failure.kind }
}

struct hb_shape_run_Outcome { value: []hb.Glyph, failure: fail.Failure, kind: fail.Kind }
fn hb_shape_run(a0: *mem.Arena, p0: *const hb.Api, p1: rawptr, p2: []const u8, p3: hb.Options, p4: []const hb.Feature) hb_shape_run_Outcome {
  status: fail.Status
  value := hb.shape_run(a0, &status, p0, p1, p2, p3, p4)
  return hb_shape_run_Outcome{ value: value, failure: status.failure, kind: status.failure.kind }
}

struct hb_load_Outcome { api: hb.Api, failure: fail.Failure, kind: fail.Kind }
fn hb_load(p0: dynlib.Handle) hb_load_Outcome {
  status: fail.Status
  value := hb.load(&status, p0)
  return hb_load_Outcome{ api: value, failure: status.failure, kind: status.failure.kind }
}

struct dynlib_open_Outcome { value: dynlib.Handle, failure: fail.Failure, kind: fail.Kind }
fn dynlib_open(p0: []const u8, p1: i32) dynlib_open_Outcome {
  status: fail.Status
  value := dynlib.open(&status, p0, p1)
  return dynlib_open_Outcome{ value: value, failure: status.failure, kind: status.failure.kind }
}

struct dynlib_close_Outcome { failure: fail.Failure, kind: fail.Kind }
fn dynlib_close(p0: *dynlib.Handle) dynlib_close_Outcome {
  status: fail.Status
  dynlib.close(&status, p0)
  return dynlib_close_Outcome{ failure: status.failure, kind: status.failure.kind }
}

struct software_render_Outcome { failure: fail.Failure, kind: fail.Kind }
fn software_render(p0: *software.Surface, p1: *const ui.Command, p2: software.Font) software_render_Outcome {
  status: fail.Status
  software.render(&status, p0, p1, p2)
  return software_render_Outcome{ failure: status.failure, kind: status.failure.kind }
}

fn failed(failure: fail.Failure) bool {
  return failure.kind != fail.Kind.Ok
}

fn check(ok: bool){if !ok {#panic("font vendor contract")}}
fn save(arena: *mem.Arena, glyphs: []const hb.Glyph, path: []const u8){
 output := mem.push_array<u8>(arena, 4+glyphs.len*24)
 binary.store_u32_le(output[..4],#cast(u32,glyphs.len))
 for i in 0..glyphs.len{glyph := glyphs[i]
 values: [6]u32 = [glyph.index,glyph.cluster,#cast(u32,glyph.x_advance),#cast(u32,glyph.y_advance),#cast(u32,glyph.x_offset),#cast(u32,glyph.y_offset)]
 for j in 0..6 {binary.store_u32_le(output[4+i*24+j*4..8+i*24+j*4],values[j])}}
 check(fs_write_file(path,output))
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
 arena := mem.arena_alloc(0)
 defer {mem.arena_release(arena)}
 library := dynlib_open("FT_LIBRARY",dynlib.Now)
 check(!failed(library.failure))
 defer {_ = dynlib_close(&library.value)}
 ft_loaded := ft_load(library.value)
 check(!failed(ft_loaded.failure) && failed(ft_load(nil).failure))
 font_bytes_file: fail.Status
 font_bytes := fs.read_all(arena, &font_bytes_file, "font.ttf", 10000000)
 check(!font_bytes_file.failed)
 font := ft.Font{}
 check(!failed(ft_open(&font,ft_loaded.api,font_bytes,0,32).failure))
 defer {ft.close(&font)}
 check(ft_open(&font,ft_loaded.api,font_bytes,0,32).kind == fail.Kind.InvalidState)
 index := ft_loaded.api.char_index(font.face,65)
 check(index != 0 && ft_loaded.api.load_glyph(font.face,index,ft.LoadRender) == 0)
 bitmap := ft_bitmap(font.face)
 check(!failed(bitmap.failure) && bitmap.value.width > 0 && bitmap.value.height > 0)
 value := bitmap.value
 output := mem.push_array<u8>(arena, 24+#cast(usize,value.width)*#cast(usize,value.height))
 fields: [6]u32 = [#cast(u32,value.width),#cast(u32,value.height),#cast(u32,value.left),#cast(u32,value.top),#cast(u32,value.advance_x),#cast(u32,value.advance_y)]
 for i in 0..6 {binary.store_u32_le(output[i*4..i*4+4],fields[i])}
 for row in 0..value.height {for x in 0..value.width {output[24+#cast(usize,row*value.width+x)] = value.pixels[#cast(usize,row)*value.stride+#cast(usize,x)]}}
 check(fs_write_file("ft-actual.bin",output))
 metrics:=ft_face_metrics(font.face)
 check(!failed(metrics.failure) && ft_face_metrics(nil).kind==fail.Kind.InvalidInput)
 values:=metrics.value
 metric_fields:[7]u32=[#cast(u32,values.units_per_em),#cast(u32,#cast(i32,values.ascent)),#cast(u32,#cast(i32,values.descent)),#cast(u32,#cast(i32,values.height)),values.glyph_count,values.face_count,values.face_index]
 metric_bytes:[28]u8
 for i in 0..7 {binary.store_u32_le(metric_bytes[i*4..i*4+4],metric_fields[i])}
 check(fs_write_file("metrics-actual.bin",metric_bytes[..]))
 shaping := dynlib_open("HB_LIBRARY",dynlib.Now)
 check(!failed(shaping.failure))
 defer {_ = dynlib_close(&shaping.value)}
 loaded := hb_load(shaping.value)
 check(!failed(loaded.failure) && failed(hb_load(nil).failure))
 created := hb_font_owned(&loaded.api,font_bytes,0)
 check(!failed(created.failure))
 empty_font = loaded.api.font_get_empty()
 oom_api := loaded.api
 oom_api.font_create = empty_create
 oom_api.font_destroy = count_empty_destroy
 oom_api.ot_font_set_funcs = reject_empty_configuration
 failed_font := hb_font_owned(&oom_api,font_bytes,0)
 check(failed(failed_font.failure) && failed_font.kind == fail.Kind.System && failed_font.value == nil && empty_destroyed == 1)
 empty_face = loaded.api.face_get_empty()
 real_blob_destroy = loaded.api.blob_destroy
 face_oom := loaded.api
 face_oom.face_create = empty_face_create
 face_oom.face_destroy = count_empty_face_destroy
 face_oom.blob_destroy = count_blob_destroy
 face_oom.face_glyph_count = reject_empty_glyph_count
 failed_face := hb_font_owned(&face_oom,font_bytes,0)
 check(failed(failed_face.failure) && failed_face.kind == fail.Kind.System && failed_face.value == nil && empty_face_destroyed == 1 && blob_destroyed == 1)
 defer {loaded.api.font_destroy(created.value)}
 loaded.api.font_set_scale(created.value,2048,2048)
 features: []const hb.Feature
 latin := hb_shape(arena,&loaded.api,created.value,"office AV",0,features)
 arabic := hb_shape(arena,&loaded.api,created.value,"السلام",0,features)
 check(!failed(latin.failure) && latin.value.len < 9 && !failed(arabic.failure) && arabic.value.len <= 6)
 check(arabic.value[0].cluster > arabic.value[arabic.value.len-1].cluster)
 for glyph in latin.value {check(glyph.index != 0)}
 for glyph in arabic.value {check(glyph.index != 0)}
 save(arena,latin.value,"latin-actual.bin")
 save(arena,arabic.value,"arabic-actual.bin")
 run := hb_shape_run(arena,&loaded.api,created.value,"السَلام",hb.Options{direction:hb.RightToLeft,script:1098015074,language:"ar",cluster_level:hb.MonotoneCharacters,flags:hb.BeginningOfText|hb.EndOfText},features)
 check(!failed(run.failure))
 save(arena,run.value,"run-actual.bin")
 context_run:=hb_shape_run(arena,&loaded.api,created.value,"بجح",hb.Options{direction:hb.RightToLeft,script:1098015074,language:"ar",cluster_level:1,item_offset:2,has_item_length:true,item_length:2},features)
 check(!failed(context_run.failure) && context_run.value.len>0 && context_run.value[0].cluster==2)
 save(arena,context_run.value,"context-actual.bin")
 unicode := loaded.api.unicode_get_default()
 check(unicode!=nil && loaded.api.unicode_script(unicode,65)==1281455214 && loaded.api.script_horizontal_direction(1098015074)==hb.RightToLeft)
 checkpoint := mem.arena_mark(arena)
 check(hb_shape_run(arena,&loaded.api,created.value,"x",hb.Options{cluster_level:3},features).kind==fail.Kind.InvalidInput)
 check(hb_shape_run(arena,&loaded.api,created.value,"x",hb.Options{flags:256},features).kind==fail.Kind.InvalidInput)
 check(hb_shape_run(arena,&loaded.api,created.value,"x",hb.Options{language:"a\0r"},features).kind==fail.Kind.InvalidInput)
 check(hb_shape_run(arena,&loaded.api,created.value,"x",hb.Options{item_offset:2},features).kind==fail.Kind.InvalidInput)
 check(hb_shape_run(arena,&loaded.api,created.value,"x",hb.Options{has_item_length:true,item_length:2},features).kind==fail.Kind.InvalidInput)
 check(hb_shape_run(arena,&loaded.api,created.value,"x",hb.Options{has_item_length:true,item_length: -2},features).kind==fail.Kind.InvalidInput)
 check(mem.arena_mark(arena)==checkpoint)
 // The FreeType callback consumes shaped glyph IDs with baseline origins.
 adapter := ft.Adapter{font:&font,line_height:40,glyph_ids:true}
 context := ui.Context{ style: ui.default_style }
 viewport := ui.Rect{width:256,height:64}
 ui.begin(&context,arena,ui.Input{},viewport)
 pen: i64 = 20*64
 for glyph in arabic.value {ui.glyph(&context,viewport,glyph.index,(pen+#cast(i64,glyph.x_offset))/64,40-#cast(i64,glyph.y_offset)/64,ui.Color{r:255,g:255,b:255,a:255})
 pen += #cast(i64,glyph.x_advance)}
 ui.end(&context)
 pixels := mem.push_array<u8>(arena, #cast(usize,256*64*4))
 surface := software.Surface{pixels:pixels,width:256,height:64,stride:256*4}
 check(!failed(software_render(&surface,ui.first(&context),ft.renderer(&adapter)).failure))
 ink: usize = 0
 for pixel in pixels {if pixel != 0 {ink += 1}}
 check(ink > 100 && adapter.kind == fail.Kind.Ok)
 bad := ft.Font{}
 check(failed(ft_open(&bad,ft_loaded.api,"broken",0,32).failure) && bad.face == nil && bad.library == nil)
 check(hb_font_owned(&loaded.api,"broken",0).kind == fail.Kind.InvalidInput)
 check(hb_shape(arena,&loaded.api,created.value,"x",1,features).kind == fail.Kind.InvalidInput)
 ft.close(&font)
 ft.close(&font)
}

// Writes data to path; whether it worked.
fn fs_write_file(path: []const u8, data: []const u8) bool {
  status: fail.Status
  fs.write_all(&status, path, data)
  return !status.failed
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
