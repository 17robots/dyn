#!/usr/bin/env python3
"""Direct X11/GLX UI rendering; no SDL. Requires DISPLAY and desktop GL 3.3."""
import os
from pathlib import Path
import subprocess
import shutil
import sys
import shlex
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/('build/dyn-release.exe' if sys.platform=='win32' else 'build/dyn-release'))).resolve())
SOURCE = r'''use "vendor/window" window
use "vendor/opengl" gl
use "vendor/ui/opengl" gpu
use "std/ui" ui
use "std/ui/software" software
use "std/errors" errors
use "std/mem" mem
fn check(ok: bool) { if !ok { #panic("native GPU UI contract") } }
fn bitmap(data: rawptr, codepoint: u32) software.Glyph {
 _ = data
 if codepoint == 0 { return software.Glyph{width:-1} }
 coverage := "\xff\x80\x00xx\x00\x80\xff"
 return software.Glyph{pixels:coverage,width:3,height:2,stride:5,advance:4,x_offset:-1,y_offset:1}
}
struct Wide { pixels: []u8 }
fn wide_bitmap(data: rawptr, codepoint: u32) software.Glyph {
 _ = codepoint
 wide := #cast(*Wide,data)
 return software.Glyph{pixels:wide.pixels,width:#cast(i32,#len(wide.pixels)),height:1,stride:#len(wide.pixels)}
}
fn no_textures(count: i32, output: *u32) { _ = count
 output.* = 0 }
fn main() {
 host := window.Window{}
 check(!window.open(&host,"bad",0,32).ok)
 check(window.open(&host,"Dyn native renderer test",32,32).ok)
 defer { window.close(&host) }
 check(window.open(&host,"duplicate",32,32).kind == errors.Kind.InvalidState)
 loaded := gl.load(window.gl_proc)
 check(loaded.ok)
 renderer := gpu.Renderer{}
 check(gpu.open(&renderer,loaded.api).ok)
 defer { gpu.close(&renderer) }
 check(gpu.open(&renderer,loaded.api).kind == errors.Kind.InvalidState)
 commands: [5]ui.Command = [
 ui.Command{kind:ui.Kind.Rectangle,bounds:ui.Rect{width:32,height:32},clip:ui.Rect{width:32,height:32},color:ui.Color{r:10,g:20,b:30,a:255}},
 ui.Command{kind:ui.Kind.Rectangle,bounds:ui.Rect{x:2,y:3,width:12,height:9},clip:ui.Rect{x:5,y:4,width:6,height:5},color:ui.Color{r:230,g:60,b:90,a:128}},
 ui.Command{kind:ui.Kind.Text,bounds:ui.Rect{x:2,y:14,width:16,height:10},clip:ui.Rect{x:3,y:14,width:13,height:7},text:"a\na",color:ui.Color{r:255,g:240,a:255}},
 ui.Command{kind:ui.Kind.Glyph,bounds:ui.Rect{width:32,height:32},codepoint:65,glyph_x:24,glyph_y:5,clip:ui.Rect{x:24,y:6,width:1,height:2},color:ui.Color{g:255,a:128}},
 ui.Command{kind:ui.Kind.Glyph,bounds:ui.Rect{width:32,height:32},codepoint:65,glyph_x:9223372036854775807,glyph_y:0,clip:ui.Rect{width:32,height:32},color:ui.Color{r:255,a:255}}]
 for i in 0..4 { commands[i].next = &commands[i+1] }
 pixels: [4096]u8 = []
 surface := software.Surface{pixels:pixels[..],width:32,height:32,stride:128}
 font := software.Font{glyph:bitmap,line_height:3}
 check(software.render(&surface,&commands[0],font).ok)
 loaded.api.enable(gl.FramebufferSrgb)
 loaded.api.enable(gl.ColorLogicOp)
 loaded.api.enable(gl.RasterizerDiscard)
 loaded.api.enable(gl.Dither)
 loaded.api.enable(gl.ClipDistance0)
 loaded.api.color_mask(0,0,0,0)
 loaded.api.polygon_mode(gl.FrontAndBack,0x1b01)
 check(gpu.render(&renderer,&commands[0],32,32,font).ok)
 check(loaded.api.is_enabled(gl.RasterizerDiscard) == 0 && loaded.api.is_enabled(gl.FramebufferSrgb) == 0 && loaded.api.is_enabled(gl.ColorLogicOp) == 0 && loaded.api.is_enabled(gl.Dither) == 0 && loaded.api.is_enabled(gl.ClipDistance0) == 0)
 actual: [4096]u8 = []
 loaded.api.read_pixels(0,0,32,32,gl.Rgba,gl.UnsignedByte,&actual[0])
 for y in 0..32 {
 for x in 0..32 {
 for channel in 0..4 {
 expected := #cast(i32,pixels[(y*32+x)*4+channel])
 got := #cast(i32,actual[((31-y)*32+x)*4+channel])
 difference := expected-got
 check(difference >= -1 && difference <= 1)
 }
 }
 }
 check(loaded.api.get_error() == 0)
 // A glyph wider than hardware textures succeeds when only one pixel is visible.
 arena := mem.Arena{}
 defer { mem.arena_release(&arena) }
 check(renderer.max_texture > 0 && renderer.max_texture < 1048576)
 wide := Wide{pixels:mem.push_array(u8,&arena,#cast(usize,renderer.max_texture)+1)}
 wide.pixels[0] = 255
 single := ui.Command{kind:ui.Kind.Glyph,bounds:ui.Rect{width:32,height:32},clip:ui.Rect{x:2,y:2,width:1,height:1},glyph_x:2,glyph_y:2,color:ui.Color{r:255,a:255}}
 check(gpu.render(&renderer,&single,32,32,software.Font{data:&wide,glyph:wide_bitmap,line_height:1}).ok)
 pixel: [4]u8 = []
 loaded.api.read_pixels(2,29,1,1,gl.Rgba,gl.UnsignedByte,&pixel[0])
 check(pixel[0] == 255 && pixel[1] == 0 && pixel[2] == 0 && pixel[3] == 255 && loaded.api.get_error() == 0)
 loaded.api.enable(0xffffffff)
 check(gpu.render(&renderer,&commands[0],32,32,font).kind == errors.Kind.System && loaded.api.get_error() == 0)
 broken := loaded.api
 broken.gen_textures = no_textures
 rejected := gpu.Renderer{}
 check(gpu.open(&rejected,broken).kind == errors.Kind.System && rejected.program == 0)
 check(window.poll(&host).ok && window.swap(&host).ok)
 bad := commands[3]
 bad.codepoint = 0
 check(gpu.render(&renderer,&bad,32,32,font).kind == errors.Kind.InvalidInput)
 gpu.close(&renderer)
 gpu.close(&renderer)
 check(gpu.render(&renderer,&commands[0],32,32,font).kind == errors.Kind.InvalidState)
 window.close(&host)
 window.close(&host)
 check(!window.poll(&host).ok && !window.swap(&host).ok)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-native-ui-') as directory:
    work = Path(directory)
    if sys.platform=='win32' and os.environ.get('DYN_OPENGL_DLL'):
        # Mesa's Windows llvmpipe deployment requires both DLLs beside the exe.
        driver=Path(os.environ['DYN_OPENGL_DLL']).resolve()
        shutil.copy2(driver,work/'opengl32.dll')
        shutil.copy2(driver.parent/'libgallium_wgl.dll',work/'libgallium_wgl.dll')
    backends = []
    if sys.platform.startswith('linux'):
        if os.environ.get('DISPLAY'):
            backends.append(('X11', SOURCE, []))
        else:
            print('SKIP native X11: DISPLAY unavailable')
        if os.environ.get('WAYLAND_DISPLAY') and shutil.which('wayland-scanner'):
            bridge=work/'libdyn_window.so'
            subprocess.run(['python3',str(ROOT/'vendor/window/native/build.py'),'--output',str(bridge)],check=True,timeout=60)
            backends.append(('Wayland',SOURCE.replace('use "vendor/window" window','use "vendor/window/wayland" window'),['--link',str(bridge)]))
        else:
            print('SKIP native Wayland: display or scanner unavailable')
    elif sys.platform in ('darwin','win32'):
        bridge=work/('libdyn_window.dylib' if sys.platform=='darwin' else 'dyn_window.dll')
        subprocess.run(['python3',str(ROOT/'vendor/window/native/build.py'),'--output',str(bridge)],check=True,timeout=60)
        library=bridge if sys.platform=='darwin' else work/'libdyn_window.dll.a'
        backends.append((sys.platform,SOURCE,['--link',str(library)]))
    for name,source,links in backends:
        (work/'main.dyn').write_text(source)
        for flags in (['--debug'], ['--release'], ['--release', '--opt-level', '3']):
            output = work/('program.exe' if sys.platform=='win32' else 'program')
            subprocess.run([DYN,'build',str(work),*flags,'--quiet','--no-cache',*links,'--output',str(output)],check=True,timeout=300)
            subprocess.run([str(output)],check=True,timeout=60)
        print('PASS native '+name+' UI: GPU/software pixel oracle, alpha, clips, text, positioned glyphs, atlas stride, extremes, lifetime; debug/O2/O3')
    if sys.platform.startswith('linux') and os.environ.get('DISPLAY'):
        shim=work/'glx-failure.so'
        subprocess.run([*shlex.split(os.environ.get('CC','cc')),'-shared','-fPIC','-Wall','-Wextra','-Werror',str(ROOT/'tests/x11-context-failure.c'),'-ldl','-o',str(shim)],check=True,timeout=60)
        (work/'main.dyn').write_text('use "vendor/window" window\nuse "std/errors" errors\nfn main(){ host := window.Window{}\n result := window.open(&host,"Expected failure",32,32)\n if result.ok || result.kind != errors.Kind.System || host.display != nil { #panic("GLX error was not recovered") }\n window.close(&host)\n}\n')
        output=work/'context-failure'
        subprocess.run([DYN,'build',str(work),'--debug','--quiet','--output',str(output)],check=True,timeout=300)
        subprocess.run([str(output)],env={**os.environ,'LD_PRELOAD':str(shim)},check=True,timeout=60)
        print('PASS X11 asynchronous GLX context error recovery')
    if sys.platform=='darwin':
        executable=work/'cocoa-multiwindow'
        subprocess.run([*shlex.split(os.environ.get('CC','cc')),'-fobjc-arc',str(ROOT/'tests/cocoa-window-results.m'),'-framework','Cocoa','-framework','OpenGL','-o',str(executable)],check=True,timeout=60)
        subprocess.run([str(executable)],check=True,timeout=60)
        print('PASS native Cocoa multiwindow event routing')
    (work/'main.dyn').write_text(SOURCE)
    for target in ('aarch64-linux','riscv64-linux','x86_64-windows','aarch64-windows','x86_64-macos','aarch64-macos'):
        subprocess.run([DYN,'build',str(work),'--target',target,'--release','--quiet','--no-link','--emit-object','--output',str(work/target)],check=True,timeout=300)
    if sys.platform.startswith('linux') and shutil.which('zig'):
        for target in ('x86_64-windows-gnu','aarch64-windows-gnu'):
            subprocess.run(['zig','cc','-target',target,'-c','-Wall','-Wextra','-Werror',str(ROOT/'vendor/window/native/win32.c'),'-o',str(work/(target+'.o'))],check=True,timeout=120)
        if shutil.which('wine') and os.environ.get('DISPLAY'):
            bridge=work/'dyn_window.dll';library=work/'libdyn_window.dll.a'
            subprocess.run(['zig','cc','-target','x86_64-windows-gnu','-shared',str(ROOT/'vendor/window/native/win32.c'),'-luser32','-lgdi32','-lopengl32','-Wl,--out-implib,'+str(library),'-o',str(bridge)],check=True,timeout=180)
            for flags in (['--debug'], ['--release'], ['--release','--opt-level','3']):
                output=work/'program.exe'
                subprocess.run([DYN,'build',str(work),'--target','x86_64-windows',*flags,'--quiet','--no-cache','--link',str(library),'--output',str(output)],check=True,timeout=300)
                subprocess.run(['wine',str(output)],env={**os.environ,'WINEDEBUG':'-all'},check=True,timeout=60,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            print('PASS Wine WGL UI: same GPU/software oracle and lifecycle; debug/O2/O3 (native Windows remains separate qualification)')
print('PASS window/UI six-target Dyn object builds; Cocoa native SDK/execution requires macOS CI')
