#!/usr/bin/env python3
"""Actual Vulkan compute UI oracle, including transparent destinations."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use "vendor/ui/vulkan" gpu
use "std/ui" ui
use "std/ui/software" software
use "std/mem" mem
use "std/errors" errors
fn check(ok: bool) { if !ok { #panic("Vulkan UI contract") } }
struct FontData { pixels: [8]u8 }
fn bitmap(data: rawptr, codepoint: u32) software.Glyph {
 if codepoint == 0 { return software.Glyph{width:-1} }
 font := #cast(*FontData,data)
 font.pixels = [255,#cast(u8,codepoint),0,10,20,0,128,255]
 return software.Glyph{pixels:font.pixels[..],width:3,height:2,stride:5,advance:4,x_offset:-1,y_offset:1}
}
fn main() {
 arena := mem.arena_create(0)
 defer { mem.arena_release(arena) }
 renderer := gpu.Renderer{}
 check(gpu.open(&renderer,gpu.Limits{}).ok)
 defer { gpu.close(&renderer) }
 check(gpu.open(&renderer,gpu.Limits{}).kind == errors.Kind.InvalidState)
 commands: [5]ui.Command = [
 ui.Command{kind:ui.Kind.Rectangle,bounds:ui.Rect{x:2,y:3,width:12,height:9},clip:ui.Rect{x:5,y:4,width:6,height:5},color:ui.Color{r:230,g:60,b:90,a:128}},
 ui.Command{kind:ui.Kind.Rectangle,bounds:ui.Rect{x:4,y:4,width:12,height:9},clip:ui.Rect{width:32,height:32},color:ui.Color{r:80,g:220,b:30,a:70}},
 ui.Command{kind:ui.Kind.Text,bounds:ui.Rect{x:2,y:14,width:16,height:10},clip:ui.Rect{x:3,y:14,width:13,height:7},text:"ab\ncd",color:ui.Color{r:255,g:240,a:255}},
 ui.Command{kind:ui.Kind.Glyph,bounds:ui.Rect{width:32,height:32},codepoint:65,glyph_x:24,glyph_y:5,clip:ui.Rect{x:24,y:6,width:1,height:2},color:ui.Color{g:255,a:128}},
 ui.Command{kind:ui.Kind.Glyph,bounds:ui.Rect{width:32,height:32},codepoint:65,glyph_x:9223372036854775807,glyph_y:0,clip:ui.Rect{width:32,height:32},color:ui.Color{r:255,a:255}}]
 for i in 0..4 { commands[i].next = &commands[i+1] }
 font_data := FontData{}
 font := software.Font{data:&font_data,glyph:bitmap,line_height:3}
 pixels: [4224]u8 = []
 actual: [4224]u8 = []
 for i in 0..#len(pixels) { pixels[i] = #cast(u8,i*37+19)
 actual[i] = pixels[i] }
 surface := software.Surface{pixels:pixels[..],width:32,height:32,stride:132}
 target := software.Surface{pixels:actual[..],width:32,height:32,stride:132}
 check(software.render(&surface,&commands[0],font).ok)
 check(gpu.render(&renderer,arena,&target,&commands[0],font).ok)
 for i in 0..#len(pixels) { check(pixels[i] == actual[i]) }
 // Reuse persistent GPU buffer on a smaller frame.
 surface.width = 7
 surface.height = 5
 target.width = 7
 target.height = 5
 check(software.render(&surface,&commands[0],font).ok)
 check(gpu.render(&renderer,arena,&target,&commands[0],font).ok)
 for i in 0..#len(pixels) { check(pixels[i] == actual[i]) }
 renderer.limits.draws = 0
 check(gpu.render(&renderer,arena,&target,&commands[0],font).kind == errors.Kind.Capacity)
 renderer.limits = gpu.Limits{coverage_bytes:0}
 target.width = 32
 target.height = 32
 check(gpu.render(&renderer,arena,&target,&commands[2],font).kind == errors.Kind.Capacity)
 renderer.limits = gpu.Limits{}
 bad := commands[3]
 bad.codepoint = 0
 check(gpu.render(&renderer,arena,&target,&bad,font).kind == errors.Kind.InvalidInput)
 target.stride = 0
 check(gpu.render(&renderer,arena,&target,&commands[0],font).kind == errors.Kind.InvalidInput)
 gpu.close(&renderer)
 gpu.close(&renderer)
 check(gpu.render(&renderer,arena,&target,&commands[0],font).kind == errors.Kind.InvalidState)
}
'''
if not shutil.which('glslangValidator'):
    print('SKIP Vulkan UI: glslangValidator unavailable');raise SystemExit(0)
headers=ROOT/'build/vendor-deps/install/include'
if not (headers/'vulkan/vulkan.h').exists() and not Path('/usr/include/vulkan/vulkan.h').exists():
    print('SKIP Vulkan UI: Vulkan headers unavailable');raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-vulkan-ui-') as directory:
    work=Path(directory);(work/'main.dyn').write_text(SOURCE)
    library=work/'libdyn_ui_vulkan.so'
    subprocess.run(['python3',str(ROOT/'vendor/ui/vulkan/native/build.py'),'--output',str(library),'--include',str(headers)],check=True,timeout=60)
    for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
        output=work/'program'
        subprocess.run([DYN,'build',str(work),*flags,'--quiet','--no-cache','--link',str(library),'--output',str(output)],check=True,timeout=300)
        subprocess.run([str(output)],check=True,timeout=60)
    for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows'):
        subprocess.run([DYN,'build',str(work),'--target',target,'--release','--quiet','--no-link','--emit-object','--output',str(work/target)],check=True,timeout=300)
print('PASS Vulkan UI: actual GPU/software exact pixel oracle, transparent alpha, clips, text, copied borrowed glyphs, padded stride, reuse, budgets, errors; debug/O2/O3 + Dyn cross-objects')
