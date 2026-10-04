#!/usr/bin/env python3
"""Standalone Linux media/transfer/grammar provider qualification.

All workflows and the combined C ABI oracle are required by default; missing
providers/fonts fail. --providers selects an explicit subset. No downloads.
Compiler-owned fixtures replace sibling example and test dependencies.
"""
import argparse
import http.server
import json
import os
import platform
from pathlib import Path
import shlex
import struct
import subprocess
import tempfile
import threading
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get('BUILD', ROOT/'build')).resolve()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--providers', nargs='+', help='Explicit workflow subset; default requires all media providers')
options = parser.parse_args()
if platform.system() != 'Linux':
    raise RuntimeError('Media qualification requires native Linux')
env = dict(os.environ)
local = BUILD/'vendor-deps/install'
for key, suffix in [('PKG_CONFIG_PATH', 'lib/pkgconfig'), ('DYN_LIBRARY_PATH', 'lib'), ('LD_LIBRARY_PATH', 'lib')]:
    env[key] = str(local/suffix) + (os.pathsep + env[key] if env.get(key) else '')
dyn = str(Path(env.get('DYN', BUILD/'dyn-release')).resolve())
FIXTURES = {
    'tree-sitter-example': r'''use "vendor/tree_sitter" ts
use "std/strings"
use "std/io"
// Grammar is separate from runtime. This example uses the packaged C grammar.
#link("tree-sitter-c")
extern fn language "tree_sitter_c"() ts.Language
fn main() {
  parser := ts.parser_create_owned()
  if parser == nil {
    #panic("parser allocation")
  }
  defer ts.parser_destroy_owned(parser)
  if !ts.parser_language(parser, language()) {
    #panic("grammar ABI mismatch")
  }
  parsed := ts.parse(parser, nil, "int x;")
  if !parsed.ok {
    #panic("parse")
  }
  defer ts.tree_destroy_owned(parsed.tree)
  node := ts.root(parsed.tree)
  kind := ts.node_type(node, 128)
  if !kind.ok || !strings.equal(kind.value, "translation_unit") || ts.node_has_error(node) {
    #panic("root")
  }
  if ts.node_end(node) != 6 || ts.child_count(node) != 1 {
    #panic("range")
  }
  if ts.node_valid(ts.child(node, 99)) {
    #panic("missing child")
  }
  copied := ts.tree_copy_owned(parsed.tree)
  if copied == nil {
    #panic("copy")
  }
  defer ts.tree_destroy_owned(copied)
  edit := ts.Edit{ start_byte: 4, old_end_byte: 5, new_end_byte: 7, start_point: ts.Point{ column: 4 }, old_end_point: ts.Point{ column: 5 }, new_end_point: ts.Point{ column: 7 } }
  if !ts.tree_edit(parsed.tree, &edit) {
    #panic("edit")
  }
  reparsed := ts.parse(parser, parsed.tree, "int xyz;")
  if !reparsed.ok {
    #panic("reparse")
  }
  defer ts.tree_destroy_owned(reparsed.tree)
  if ts.node_end(ts.root(reparsed.tree)) != 8 || ts.node_has_error(ts.root(reparsed.tree)) {
    #panic("incremental parse")
  }
  if ts.node_end(ts.root(copied)) != 6 {
    #panic("copy changed")
  }
  malformed := ts.parse(parser, nil, "int = ;")
  if !malformed.ok {
    #panic("error tree")
  }
  defer ts.tree_destroy_owned(malformed.tree)
  if !ts.node_has_error(ts.root(malformed.tree)) {
    #panic("syntax error missing")
  }
  _ = io.println(io.stdout(), "Tree-sitter: parsed, traversed, copied and incrementally reparsed C")
}
''',
    'regex-example': r'''use "vendor/pcre2" regex
use "std/strings"
use "std/io"
fn main() {
  compiled := regex.compile_owned("name=([a-z]+)", 0)
  if !compiled.ok {
    #panic("regex compile")
  }
  defer regex.pattern_destroy_owned(compiled.pattern)
  data := regex.match_data_create_owned(compiled.pattern)
  if data == nil {
    #panic("match allocation")
  }
  defer regex.match_data_destroy_owned(data)
  subject := "name=ada"
  matched := regex.match(compiled.pattern, data, subject, 0)
  if !matched.ok || !matched.matched {
    #panic("match")
  }
  span := regex.capture(data, 1)
  if !span.set || !strings.equal(subject[span.start..span.end], "ada") {
    #panic("capture")
  }
  absent := regex.match(compiled.pattern, data, "123", 0)
  if !absent.ok || absent.matched {
    #panic("no-match status")
  }
  if regex.match(compiled.pattern, data, subject, 999).ok {
    #panic("start validation")
  }
  invalid := regex.compile_owned("(", 0)
  if invalid.ok {
    regex.pattern_destroy_owned(invalid.pattern)
    #panic("invalid pattern accepted")
  }
  unicode := regex.compile_owned("(.)?", regex.Utf | regex.Ucp)
  if !unicode.ok {
    #panic("Unicode compile")
  }
  defer regex.pattern_destroy_owned(unicode.pattern)
  unicode_data := regex.match_data_create_owned(unicode.pattern)
  if unicode_data == nil {
    #panic("Unicode match data")
  }
  defer regex.match_data_destroy_owned(unicode_data)
  bad_utf: [1]u8 = [255]
  if regex.match(unicode.pattern, unicode_data, bad_utf[..], 0).ok {
    #panic("invalid UTF accepted")
  }
  empty_match := regex.match(unicode.pattern, unicode_data, "", 0)
  if !empty_match.ok || !empty_match.matched || regex.capture(unicode_data, 1).set {
    #panic("unset capture")
  }
  _ = io.println(io.stdout(), "PCRE2: captured ada; no-match and invalid pattern handled")
}
''',
    'lua-example': r'''use "vendor/lua"
use "std/strings"
use "std/io"
fn main() {
  state := lua.create_owned()
  if state == nil {
    #panic("Lua allocation")
  }
  defer lua.destroy_owned(state)
  if !lua.execute(state, "return 6 * 7").ok {
    #panic("Lua evaluation")
  }
  answer := lua.integer(state, -1)
  if !answer.ok || answer.value != 42 {
    #panic("Lua result")
  }
  if !lua.pop(state, 1) {
    #panic("Lua pop")
  }
  if !lua.execute(state, "return 'hello'").ok {
    #panic("Lua string")
  }
  text := lua.bytes(state, -1)
  if !text.ok || !strings.equal(text.value, "hello") {
    #panic("Lua bytes")
  }
  _ = lua.pop(state, 1) // text expires here.
  if lua.execute(state, "return (").ok || lua.stack_size(state) != 1 {
    #panic("Lua syntax failure")
  }
  _ = lua.pop(state, 1)
  if lua.execute(state, "return missing()").ok {
    #panic("Lua runtime failure")
  }
  _ = lua.pop(state, 1)
  if lua.stack_size(state) != 0 || lua.pop(state, 1) {
    #panic("Lua stack balance")
  }
  if !lua.execute(state, "").ok || lua.stack_size(state) != 1 {
    #panic("empty Lua chunk")
  }
  if lua.bytes(state, -1).ok || lua.integer(state, 0).ok {
    #panic("Lua result validation")
  }
  _ = lua.pop(state, 1)
  _ = io.println(io.stdout(), "Lua: 42; protected syntax/runtime failures; balanced stack")
}
''',
    'archive-example': r'''use "vendor/archive"
use "std/mem"
use "std/fs"
use "std/os/linux"
use "std/io"
fn main() {
  storage := mem.arena_create(16 * 1024 * 1024)
  if !storage.ok {
    #panic("arena")
  }
  defer {
    _ = mem.arena_release(&storage.arena)
  }
  args := linux.process_arguments(&storage.arena)
  if #len(args) != 2 {
    _ = io.println(io.stdout(), "usage: archive-example ARCHIVE")
    return
  }
  loaded := fs.read_all(&storage.arena, args[1], 8 * 1024 * 1024)
  if !loaded.ok {
    #panic("read archive")
  }
  opened := archive.open_memory_owned(loaded.data)
  if !opened.ok {
    #panic("open archive")
  }
  defer {
    _ = archive.destroy_owned(opened.reader)
  }
  buffer: [4096]u8 = []
  for true {
    entry := archive.next(opened.reader)
    if entry.end {
      break
    }
    if !entry.ok {
      #panic("archive header")
    }
    name := archive.entry_name(entry.entry, 4096)
    if !name.ok {
      #panic("archive name")
    }
    _ = io.println(io.stdout(), "{}", name.value)
    for true {
      read := archive.read(opened.reader, buffer[..])
      if !read.ok {
        #panic("archive data")
      }
      if read.end {
        break
      }
      _ = io.write(io.stdout(), buffer[..read.count])
    }
  }
}
''',
    'curl-example': r'''use "vendor/curl"
use "std/mem"
use "std/os/linux"
use "std/io"
fn main() {
  storage: [65536]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  args := linux.process_arguments(&arena)
  if #len(args) != 2 {
    _ = io.println(io.stdout(), "usage: curl-example URL")
    return
  }
  if curl.init() != 0 {
    #panic("curl initialization")
  }
  defer curl.cleanup()
  url: [4096]u8 = []
  response: [16384]u8 = []
  result := curl.get_into(args[1], url[..], response[..], 5000)
  if !result.ok {
    #panic("HTTP transfer failed or buffer full")
  }
  _ = io.println(io.stdout(), "HTTP {}", result.http_status)
  _ = io.write(io.stdout(), response[..result.written])
}
''',
    'sdl3-image-example': r'''use "vendor/sdl3"
use "vendor/sdl3/image" image
use "std/mem"
use "std/fs"
use "std/os/linux"
use "std/io"
fn main() {
  storage := mem.arena_create(16 * 1024 * 1024)
  if !storage.ok {
    #panic("arena")
  }
  defer {
    _ = mem.arena_release(&storage.arena)
  }
  args := linux.process_arguments(&storage.arena)
  if #len(args) != 2 {
    _ = io.println(io.stdout(), "usage: sdl3-image-example IMAGE")
    return
  }
  path: [4096]u8 = []
  surface := image.load_owned(args[1], path[..])
  if !surface.ok {
    #panic("image load")
  }
  defer sdl3.surface_destroy_owned(surface.value)
  bytes := fs.read_all(&storage.arena, args[1], 8 * 1024 * 1024)
  if !bytes.ok {
    #panic("image read")
  }
  decoded := image.decode_owned(bytes.data)
  if !decoded.ok {
    #panic("image decode")
  }
  defer sdl3.surface_destroy_owned(decoded.value)
  if image.decode_owned("not an image").ok {
    #panic("malformed image accepted")
  }
  _ = io.println(io.stdout(), "SDL_image: loaded file and decoded caller buffer")
}
''',
    'sdl3-font-example': r'''use "vendor/sdl3"
use "vendor/sdl3/ttf" ttf
use "std/mem"
use "std/os/linux"
use "std/io"
fn main() {
  storage: [65536]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  args := linux.process_arguments(&arena)
  if #len(args) != 2 {
    _ = io.println(io.stdout(), "usage: sdl3-font-example FONT.ttf")
    return
  }
  if !ttf.init() {
    #panic("font init")
  }
  defer ttf.quit()
  path: [4096]u8 = []
  font := ttf.open_owned(args[1], path[..], 20.0)
  if !font.ok {
    #panic("font open")
  }
  defer ttf.destroy_owned(font.value)
  empty := ttf.measure(font.value, "")
  if !empty.ok || empty.width != 0 {
    #panic("empty text")
  }
  measured := ttf.measure(font.value, "Hello Dyn")
  if !measured.ok || measured.width <= 0 || measured.height <= 0 {
    #panic("font measure")
  }
  surface := ttf.render_owned(font.value, "Hello Dyn", sdl3.Color{ red: 255, green: 255, blue: 255, alpha: 255 })
  if !surface.ok {
    #panic("font render")
  }
  defer sdl3.surface_destroy_owned(surface.value)
  if ttf.open_owned(args[1], path[..], 0.0).ok {
    #panic("font size validation")
  }
  _ = io.println(io.stdout(), "SDL_ttf: measured and rendered text")
}
''',
    'opengl-example': r'''use "vendor/sdl3"
use "vendor/opengl" gl
use "std/mem"
use "std/os/linux"
use "std/strings"
use "std/io"
fn shader(api: *gl.Api, kind: u32, source: []const u8) u32 {
  value := api.create_shader(kind)
  if value == 0 {
    #panic("create shader")
  }
  pointer := &source[0]
  length := #cast(i32) #len(source)
  api.shader_source(value, 1, &pointer, &length)
  api.compile_shader(value)
  compiled: i32 = 0
  api.get_shader_iv(value, gl.CompileStatus, &compiled)
  if compiled == 0 {
    log: [2048]u8 = []
    written: i32 = 0
    api.get_shader_log(value, 2048, &written, &log[0])
    if written > 0 && written <= 2048 {
      _ = io.println(io.stderr(), "{}", log[..#cast(usize) written])
    }
    api.delete_shader(value)
    #panic("compile shader")
  }
  return value
}
fn missing_proc(name: *const u8) rawptr {
  return nil
}
fn main() {
  missing := gl.load(&missing_proc)
  if missing.ok || !strings.equal(missing.missing, "glClearColor") {
    #panic("missing symbol accepted")
  }
  if gl.load(nil).ok {
    #panic("nil loader accepted")
  }
  backing: [65536]u8 = []
  arena := mem.arena_from_buffer(backing[..])
  args := linux.process_arguments(&arena)
  smoke := #len(args) == 2 && strings.equal(args[1], "--smoke")
  if !sdl3.init_video() {
    #panic("video unavailable")
  }
  defer sdl3.quit()
  if !sdl3.gl_request_core(3, 3) {
    #panic("GL attributes")
  }
  title: [64]u8 = []
  window := sdl3.window_create("Dyn OpenGL triangle", title[..], 640, 480, sdl3.WindowOpenGL | sdl3.WindowResizable)
  if !window.ok {
    #panic("GL window")
  }
  defer sdl3.window_destroy_owned(window.value)
  context := sdl3.gl_create_owned(window.value)
  if context == nil {
    #panic("GL context")
  }
  defer {
    _ = sdl3.gl_destroy_owned(context)
  }
  if !sdl3.gl_make_current(window.value, context) {
    #panic("GL current")
  }
  loaded := gl.load(&sdl3.gl_proc)
  if !loaded.ok {
    _ = io.println(io.stderr(), "missing {}", loaded.missing)
    #panic("GL load")
  }
  api := &loaded.api
  major: i32 = 0
  minor: i32 = 0
  profile: i32 = 0
  api.get_integer(33307, &major)
  api.get_integer(33308, &minor)
  api.get_integer(37158, &profile)
  if major < 3 || (major == 3 && minor < 3) || (profile & 1) == 0 {
    #panic("GL 3.3 core required")
  }
  if smoke {
    invalid := api.create_shader(gl.VertexShader)
    if invalid == 0 {
      #panic("test shader")
    }
    bad_source := "this is not GLSL"
    bad_pointer := &bad_source[0]
    bad_length := #cast(i32) #len(bad_source)
    api.shader_source(invalid, 1, &bad_pointer, &bad_length)
    api.compile_shader(invalid)
    compiled: i32 = 0
    api.get_shader_iv(invalid, gl.CompileStatus, &compiled)
    log: [2048]u8 = []
    written: i32 = 0
    api.get_shader_log(invalid, 2048, &written, &log[0])
    api.delete_shader(invalid)
    if compiled != 0 || written <= 0 || written > 2048 {
      #panic("shader diagnostics")
    }
  }
  _ = sdl3.gl_swap_interval(1)
  vertex := shader(api, gl.VertexShader, "#version 330 core\nlayout(location=0) in vec2 p; void main(){gl_Position=vec4(p,0,1);}")
  defer api.delete_shader(vertex)
  fragment := shader(api, gl.FragmentShader, "#version 330 core\nout vec4 color; void main(){color=vec4(1,0,0,1);}")
  defer api.delete_shader(fragment)
  program := api.create_program()
  if program == 0 {
    #panic("program")
  }
  defer api.delete_program(program)
  api.attach_shader(program, vertex)
  api.attach_shader(program, fragment)
  api.link_program(program)
  linked: i32 = 0
  api.get_program_iv(program, gl.LinkStatus, &linked)
  if linked == 0 {
    #panic("link program")
  }
  vao: u32 = 0
  vbo: u32 = 0
  api.gen_vertex_arrays(1, &vao)
  api.gen_buffers(1, &vbo)
  defer api.delete_vertex_arrays(1, &vao)
  defer api.delete_buffers(1, &vbo)
  api.bind_vertex_array(vao)
  api.bind_buffer(gl.ArrayBuffer, vbo)
  vertices: [6]f32 = [-0.8, -0.8, 0.8, -0.8, 0.0, 0.8]
  api.buffer_data(gl.ArrayBuffer, #cast(isize) #sizeof(vertices), #cast(rawptr) &vertices[0], gl.StaticDraw)
  api.enable_vertex_attribute(0)
  api.vertex_attribute(0, 2, gl.Float, 0, 8, nil)
  event := sdl3.Event{}
  running := true
  frames: u32 = 0
  for running {
    for sdl3.poll_event(&event) {
      if sdl3.event_requests_close(&event) {
        running = false
      }
    }
    if !running {
      break
    }
    width: i32 = 0
    height: i32 = 0
    if !sdl3.window_pixel_size(window.value, &width, &height) {
      #panic("pixel size")
    }
    api.viewport(0, 0, width, height)
    api.clear_color(0.0, 0.0, 1.0, 1.0)
    api.clear(gl.ColorBufferBit)
    api.use_program(program)
    api.draw_arrays(gl.Triangles, 0, 3)
    if smoke {
      pixel: [4]u8 = []
      api.read_pixels(width / 2, height / 2, 1, 1, gl.Rgba, gl.UnsignedByte, #cast(rawptr) &pixel[0])
      if pixel[0] < 200 || pixel[1] > 30 || pixel[2] > 30 {
        #panic("triangle pixel mismatch")
      }
    }
    if api.get_error() != 0 {
      #panic("GL error")
    }
    if !sdl3.gl_swap(window.value) {
      #panic("GL swap")
    }
    frames += 1
    if smoke && frames == 3 {
      running = false
    }
  }
  _ = io.println(io.stdout(), "OpenGL: triangle rendered; resources released on exit")
}
''',
    'curl-contract': r'''use "vendor/curl"
use "std/mem"
use "std/os/linux"
use "std/strings"
fn main() {
  backing: [65536]u8 = [] arena := mem.arena_from_buffer(backing[..])
  args := linux.process_arguments(&arena)
  if #len(args) != 3 { #panic("URL required") }
  if curl.init() != 0 { #panic("init") }
  defer curl.cleanup()
  url: [4096]u8 = [] output: [256]u8 = []
  result := curl.get_into(args[1], url[..], output[..], 5000)
  if !result.ok || result.http_status != 200 || !strings.equal(output[..result.written], "vendor transfer\n") { #panic("transfer") }
  missing := curl.get_into(args[2], url[..], output[..], 5000)
  if !missing.ok || missing.http_status != 404 { #panic("HTTP status is not transport error") }
  small: [1]u8 = []
  overflow := curl.get_into(args[1], url[..], small[..], 5000)
  if overflow.ok || !overflow.capacity_exceeded || overflow.written > 1 { #panic("bounded output") }
  if curl.get_into(args[1], small[..], output[..], 5000).ok { #panic("URL capacity") }
  if curl.get_into("http://invalid\x00suffix", url[..], output[..], 5000).ok { #panic("URL NUL") }
  if curl.get_into(args[1], url[..], output[..], 0).ok { #panic("timeout validation") }
  if curl.get_into("file:///etc/passwd", url[..], output[..], 5000).ok { #panic("protocol restriction") }
}
''',
    'provider-abi': r'''use "vendor/tree_sitter" ts
use "vendor/sdl3"
use "vendor/sdl3/image" image
use "vendor/sdl3/ttf" ttf
use "std/mem"
use "std/os/linux"
extern fn node_size "oracle_node_size"() usize
extern fn node_align "oracle_node_align"() usize
extern fn edit_size "oracle_edit_size"() usize
extern fn color_size "oracle_color_size"() usize
extern fn surface_valid "oracle_surface"(surface: sdl3.Surface) i32
fn main() {
  if #sizeof(ts.Node) != node_size() || #alignof(ts.Node) != node_align() || #sizeof(ts.Edit) != edit_size() || #sizeof(sdl3.Color) != color_size() { #panic("provider ABI mismatch") }
  backing: [65536]u8 = [] arena := mem.arena_from_buffer(backing[..])
  args := linux.process_arguments(&arena) if #len(args) != 3 { #panic("image and font paths required") }
  buffer: [4096]u8 = [] surface := image.load_owned(args[1], buffer[..])
  if !surface.ok { #panic("image") }
  defer sdl3.surface_destroy_owned(surface.value)
  if surface_valid(surface.value) == 0 { #panic("image dimensions") }
  if !ttf.init() { #panic("TTF init") }
  defer ttf.quit()
  font := ttf.open_owned(args[2], buffer[..], 18.0) if !font.ok { #panic("font") }
  defer ttf.destroy_owned(font.value)
  rendered := ttf.render_owned(font.value, "Dyn", sdl3.Color{ red: 255, green: 127, blue: 64, alpha: 255 })
  if !rendered.ok { #panic("rendered text") }
  defer sdl3.surface_destroy_owned(rendered.value)
  if surface_valid(rendered.value) == 0 { #panic("text dimensions") }
  if !sdl3.init_video() { #panic("video") }
  defer sdl3.quit()
  window := sdl3.window_create("provider test", buffer[..], 64, 64, sdl3.WindowHidden)
  if !window.ok { #panic("window") }
  defer sdl3.window_destroy_owned(window.value)
  renderer := sdl3.renderer_create_default_owned(window.value)
  if !renderer.ok { #panic("renderer") }
  defer sdl3.renderer_destroy_owned(renderer.value)
  texture := sdl3.texture_from_surface_owned(renderer.value, surface.value)
  if !texture.ok { #panic("texture") }
  defer sdl3.texture_destroy_owned(texture.value)
  if !sdl3.texture_draw(renderer.value, texture.value) || !sdl3.present(renderer.value) { #panic("draw") }
}
''',
}
ABI_ORACLE = r'''#include <stddef.h>
#include <tree_sitter/api.h>
#include <SDL3/SDL.h>
#include <SDL3_ttf/SDL_ttf.h>
#include <lua5.4/lua.h>
#include <curl/curl.h>
#define PCRE2_CODE_UNIT_WIDTH 8
#include <pcre2.h>
_Static_assert(sizeof(lua_Integer)==8 && sizeof(lua_Number)==8, "Lua default ABI required");
_Static_assert(LUA_VERSION_NUM==504, "Lua 5.4 required");
_Static_assert(PCRE2_UTF==524288 && PCRE2_UCP==131072 && PCRE2_CASELESS==8, "PCRE options");
_Static_assert(CURLOPT_URL==10002 && CURLOPT_WRITEFUNCTION==20011 && CURLOPT_WRITEDATA==10001, "curl pointer options");
_Static_assert(CURLOPT_NOSIGNAL==99 && CURLOPT_TIMEOUT_MS==155 && CURLOPT_PROTOCOLS_STR==10318 && CURLINFO_RESPONSE_CODE==2097154, "curl options");
_Static_assert(SDL_GL_CONTEXT_MAJOR_VERSION==17 && SDL_GL_CONTEXT_MINOR_VERSION==18 && SDL_GL_CONTEXT_PROFILE_MASK==20, "GL attributes");
size_t oracle_node_size(void) { return sizeof(TSNode); }
size_t oracle_node_align(void) { return _Alignof(TSNode); }
size_t oracle_edit_size(void) { return sizeof(TSInputEdit); }
size_t oracle_color_size(void) { return sizeof(SDL_Color); }
int oracle_surface(SDL_Surface *surface) { return surface && surface->w>0 && surface->h>0; }
'''

results = []

def available(packages):
    return subprocess.run(['pkg-config', '--exists', *packages], env=env).returncode == 0

def run(command, **kwargs):
    return subprocess.run(command, cwd=ROOT, env=kwargs.pop('env', env), check=True, timeout=60, **kwargs)

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'vendor transfer\n'
        self.send_response(404 if self.path == '/missing' else 200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass

with tempfile.TemporaryDirectory(prefix='dyn-vendors-') as directory:
    work = Path(directory)
    def png_chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind+data))
    image = work/'pixel.png'
    image.write_bytes(b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)) + png_chunk(b'IDAT', zlib.compress(b'\0\xff\0\0\xff')) + png_chunk(b'IEND', b''))
    archive = work/'sample.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as writer:
        writer.writestr('hello.txt', 'archive payload\n')
    invalid = work/'invalid.zip'
    invalid.write_bytes(b'not an archive')
    fonts = [Path(env['DYN_TEST_FONT'])] if env.get('DYN_TEST_FONT') else list(Path('/usr/share/fonts').rglob('DejaVuSans.ttf'))
    font = str(fonts[0]) if fonts else None
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/'
    # Avoid host proxy configuration for local deterministic transfers.
    env['NO_PROXY'] = env['no_proxy'] = '127.0.0.1'
    cases = [
        ('tree-sitter-example', ['tree-sitter', 'tree-sitter-c'], [], 'incrementally reparsed'),
        ('regex-example', ['libpcre2-8'], [], 'captured ada'),
        ('lua-example', ['lua5.4'], [], 'balanced stack'),
        ('archive-example', ['libarchive'], [str(archive)], 'hello.txt\narchive payload'),
        ('curl-example', ['libcurl'], [url], 'HTTP 200\nvendor transfer'),
        ('sdl3-image-example', ['sdl3', 'sdl3-image'], [str(image)], 'decoded caller buffer'),
        ('sdl3-font-example', ['sdl3', 'sdl3-ttf'], [font] if font else [], 'rendered text'),
        ('opengl-example', ['sdl3'], ['--smoke'], 'triangle rendered'),
    ]
    if options.providers:
        unknown = set(options.providers) - {row[0] for row in cases}
        if unknown: parser.error('Unknown workflows: '+', '.join(sorted(unknown)))
        cases = [row for row in cases if row[0] in options.providers]
    try:
        for project, dependencies, arguments, expected in cases:
            if not available(dependencies) or (project == 'sdl3-font-example' and not font):
                message = f'Missing required provider/font for {project}'
                print(message, flush=True)
                raise RuntimeError(message)
            project_dir = work/(project+'-source')
            project_dir.mkdir()
            (project_dir/'main.dyn').write_text(FIXTURES[project])
            versions = subprocess.check_output(['pkg-config', '--modversion', *dependencies], env=env, text=True).splitlines()
            for mode in ([], ['--release']):
                binary = work/project
                run([dyn, 'build', str(project_dir), '--no-cache', '--quiet', '--output', str(binary), *mode])
                runtime_env = dict(env)
                if project == 'opengl-example':
                    runtime_env['SDL_VIDEODRIVER'] = env.get('DYN_TEST_GL_DRIVER', 'offscreen')
                output = run([str(binary), *arguments], env=runtime_env, capture_output=True, text=True)
                assert expected in output.stdout, output.stdout
                if project == 'archive-example':
                    bad = subprocess.run([str(binary), str(invalid)], env=env, capture_output=True, timeout=10)
                    assert bad.returncode != 0, 'corrupt archive accepted'
                if project == 'curl-example':
                    curl_dir = work/'curl-contract'
                    curl_dir.mkdir(exist_ok=True)
                    (curl_dir/'main.dyn').write_text(FIXTURES['curl-contract'])
                    run([dyn, 'build', str(curl_dir), '--no-cache', '--quiet', '--output', str(binary), *mode])
                    run([str(binary), url, url + 'missing'])
            print(f'PASS {project}: native debug/release; metadata versions {dict(zip(dependencies, versions))}', flush=True)
            results.append(dict(project=project, status='passed', versions=dict(zip(dependencies, versions))))
        if not options.providers:
            abi_dir = work/'provider-abi'
            abi_dir.mkdir()
            (abi_dir/'main.dyn').write_text(FIXTURES['provider-abi'])
            (abi_dir/'oracle.c').write_text(ABI_ORACLE)
            oracle = work/'oracle.o'
            flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', 'tree-sitter', 'sdl3', 'sdl3-ttf', 'lua5.4', 'libcurl', 'libpcre2-8'], env=env, text=True))
            run([*shlex.split(env.get('CC', 'cc')), '-std=c11', '-c', str(abi_dir/'oracle.c'), *flags, '-o', str(oracle)])
            for mode in ([], ['--release']):
                binary = work/'abi'
                run([dyn, 'build', str(abi_dir), '--no-cache', '--quiet', '--output', str(binary), '--link', str(oracle), *mode])
                run([str(binary), str(image), font], env=dict(env, SDL_VIDEODRIVER='dummy'))
            print('PASS provider ABI/layout and SDL surface/texture integration', flush=True)
            results.append(dict(project='provider-abi', status='passed'))
    except Exception as error:
        results.append(dict(project='qualification', status='failed', error=str(error)))
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        BUILD.mkdir(parents=True, exist_ok=True)
        (BUILD/'vendor-media-results.json').write_text(json.dumps(results, indent=2)+'\n')
