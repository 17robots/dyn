#!/usr/bin/env python3
"""Native Linux adapter workflows: physics/assets/UI/network/audio.

Default requires every provider; missing dependencies fail, never skip. Fixtures
and C oracles are compiler-owned copies of the established application probes.
--providers runs an explicitly named subset and reports only those results.
"""
import argparse,json,os,platform,shlex,struct,subprocess,tempfile,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BUILD=Path(os.environ.get('BUILD',ROOT/'build')).resolve()
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--providers', nargs='+', help='Explicit subset; default runs every adapter workflow')
a=p.parse_args()
if platform.system()!='Linux':raise RuntimeError('Adapter workflows require native Linux')
env=dict(os.environ);prefix=BUILD/'vendor-deps/install'
for key,suffix in [('PKG_CONFIG_PATH','lib/pkgconfig'),('LD_LIBRARY_PATH','lib'),('DYN_LIBRARY_PATH','lib')]:env[key]=str(prefix/suffix)+(os.pathsep+env[key] if env.get(key) else '')
env['SDL_AUDIODRIVER']='dummy'
env['SDL_VIDEODRIVER']='dummy'
env['SDL_RENDER_DRIVER']='software'
dyn=str(Path(env.get('DYN',BUILD/'dyn-release')).resolve())
FIXTURES = {
    'stb': r'''use atlas "vendor/stb/rect_pack"
use image "vendor/stb/image_resize"
use "std/mem"
use "std/io"
fn resize_fails(scratch: *mem.Arena, source: []const u8, width: usize, destination: []u8, out_width: usize) bool {
  image.resize(scratch, source, width, 2, destination, out_width, out_width, 4, false) catch { return true }
  return false
}
fn packing_fails(scratch: *mem.Arena, width: usize, height: usize, rectangles: []atlas.Rectangle) bool {
  _ = atlas.pack(scratch, width, height, rectangles) catch { return true }
  return false
}
fn main() {
  backing := mem.arena_alloc(2 * 1024 * 1024)
  defer {
    mem.arena_release(backing)
  }
  rectangles: [3]atlas.Rectangle
  rectangles[0] = atlas.Rectangle{ width: 8, height: 8 }
  rectangles[1] = atlas.Rectangle{ width: 4, height: 4 }
  rectangles[2] = atlas.Rectangle{ width: 4, height: 4 }
  mark := mem.arena_mark(backing)
  if (atlas.pack(backing, 16, 16, rectangles[..]) catch 0) != 3 || mem.arena_mark(backing) != mark {
    #panic("atlas packing")
  }
  i: usize = 0
  for i < 3 {
    a := rectangles[i]
    if a.x < 0 || a.y < 0 || a.x + a.width > 16 || a.y + a.height > 16 {
      #panic("atlas bounds")
    }
    j := i + 1
    for j < 3 {
      b := rectangles[j]
      if a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height {
        #panic("atlas overlap")
      }
      j += 1
    }
    i += 1
  }
  if (atlas.pack(backing, 4, 4, rectangles[..]) catch 0) != 1 {
    #panic("atlas partial fit")
  }
  rectangles[0].width = -1
  if !packing_fails(backing, 16, 16, rectangles[..]) {
    #panic("invalid atlas rectangle")
  }
  source: [16]u8
  destination: [64]u8
  k: usize = 0
  for k < 16 {
    source[k] = 128
    k += 1
  }
  image.resize(backing, source[..], 2, 2, destination[..], 4, 4, 4, false) catch { #panic("unexpected failure") }
  for value in destination[..] {
    if value != 128 {
      #panic("resize constant color")
    }
  }
  image.resize(backing, source[..], 2, 2, destination[..], 4, 4, 4, true) catch { #panic("unexpected failure") }
  if !resize_fails(backing, source[..], 2, destination[..1], 4) || !resize_fails(backing, source[..], 2, source[..], 2) || !resize_fails(backing, source[..], 0, destination[..], 4) {
    #panic("resize bounds")
  }
  if mem.arena_mark(backing) != mark {
    #panic("scratch leak")
  }
  io.println("stb atlas and resize passed")
}
''',
    'microui-sdl3': r'''use ui "vendor/microui"
use sdl "vendor/sdl3"
use backend "vendor/sdl3/microui"
use "std/mem"
use "std/os/linux"
use io "std/io"
use "std/strings"
use "std/bytes"
use "std/time"
fn main() {
  arena := mem.arena_alloc(1024 * 1024)
  defer {
    mem.arena_release(arena)
  }
  args := linux.process_arguments(arena)
  smoke := args.len == 2 && bytes.equal(args[1], "--smoke")
  sdl.init_video() catch { #panic("unexpected failure") }
  defer sdl.quit()
  text: [256]u8
  window := sdl.window_create("Dyn interactive UI", text[..], 640, 360, sdl.WindowResizable) catch { #panic("unexpected failure") }
  defer sdl.window_destroy_owned(window)
  renderer := sdl.renderer_create_default_owned(window) catch { #panic("unexpected failure") }
  defer sdl.renderer_destroy_owned(renderer)
  context := ui.create(arena) catch { #panic("unexpected failure") }
  running := true
  clicked := false
  frame: usize = 0
  event := sdl.Event{}
  for running {
    for sdl.poll_event(&event) {
      if sdl.event_requests_close(&event) {
        running = false
      }
      _ = backend.event(context, renderer, &event)
    }
    if !running {
      break
    }
    if smoke {
      action: i32 = 0
      if frame == 2 {
        action = 1
      }
      if frame == 3 {
        action = 2
      }
      ui.mouse(context, 70, 90, action)
    }
    ui.begin(context) catch { #panic("unexpected failure") }
    if (ui.window(context, "Debug panel", text[..], ui.Rectangle{ x: 20, y: 20, width: 300, height: 220 }) catch false) {
      if clicked {
        ui.label(context, "Button clicked!", text[..]) catch { #panic("unexpected failure") }
      }
      else {
        ui.label(context, "Click the button below", text[..]) catch { #panic("unexpected failure") }
      }
      if (ui.button(context, "Click me", text[..]) catch false) {
        clicked = true
      }
      ui.window_end(context) catch { #panic("unexpected failure") }
    }
    ui.end(context) catch { #panic("unexpected failure") }
    sdl.clear(renderer, 20, 28, 48, 255) catch { #panic("unexpected failure") }
    backend.render(context, renderer) catch { #panic("unexpected failure") }
    sdl.present(renderer) catch { #panic("unexpected failure") }
    frame += 1
    if smoke && frame >= 5 {
      break
    }
    time.sleep(16 * time.Millisecond)
  }
  if smoke && !clicked {
    #panic("UI mouse click not delivered")
  }
  io.println("microui SDL rendering passed")
}
''',
    'audio-playback': r'''use audio "vendor/miniaudio"
use "std/mem"
use "std/os/linux"
use io "std/io"
use "std/strings"
use "std/bytes"
use "std/time"
fn sound_fails(arena: *mem.Arena, engine: rawptr, path: []const u8, buffer: []u8) bool {
  _ = audio.sound_create(arena, engine, path, buffer) catch { return true }
  return false
}
fn main() {
  arena := mem.arena_alloc(2 * 1024 * 1024)
  defer {
    mem.arena_release(arena)
  }
  args := linux.process_arguments(arena)
  if args.len < 2 {
    #panic("usage: audio-playback-example FILE.wav [--offline]")
  }
  offline := args.len == 3 && bytes.equal(args[2], "--offline")
  engine := audio.engine_create(arena, !offline) catch { #panic("unexpected failure") }
  defer audio.engine_close(engine)
  path: [4096]u8
  mark := mem.arena_mark(arena)
  if !sound_fails(arena, engine, "/nonexistent/dyn-audio-fixture", path[..]) || mem.arena_mark(arena) != mark {
    #panic("sound failure rollback")
  }
  sound := audio.sound_create(arena, engine, args[1], path[..]) catch { #panic("unexpected failure") }
  defer audio.sound_close(sound)
  audio.sound_volume(sound, 0.5) catch { #panic("unexpected failure") }
  negative := false
  audio.sound_volume(sound, -1.0) catch { negative = true }
  audio.sound_start(sound) catch { #panic("unexpected failure") }
  audio.sound_stop(sound) catch { #panic("unexpected failure") }
  if !negative || audio.sound_playing(sound) {
    #panic("sound controls")
  }
  audio.sound_rewind(sound) catch { #panic("unexpected failure") }
  audio.sound_start(sound) catch { #panic("unexpected failure") }
  deadline := time.deadline_after(60 * time.Second)
  samples: [2048]f32
  heard := false
  for !audio.sound_ended(sound) {
    if time.deadline_expired(&deadline) { break }
    if offline {
      count := audio.mix(engine, samples[..]) catch { #panic("unexpected failure") }
      for sample in samples[..count] {
        if sample != 0.0 {
          heard = true
        }
      }
    } else {
      time.sleep(10 * time.Millisecond)
    }
  }
  if !audio.sound_ended(sound) || (offline && !heard) {
    #panic("audio completion")
  }
  audio.sound_close(sound)
  closed := false
  audio.sound_start(sound) catch { closed = true }
  if !closed {
    #panic("closed sound accepted")
  }
  io.println("audio playback completion passed")
}
''',
    'lz4': r'''use "vendor/lz4"
use io "std/io"
use "std/bytes"
fn rejected(compress: bool, destination: []u8, source: []const u8) bool {
  if compress {
    _ = lz4.compress(destination, source) catch { return true }
    return false
  }
  _ = lz4.decompress(destination, source) catch { return true }
  return false
}
fn main() {
  compressed: [128]u8
  output: [128]u8
  source := "caller buffers caller buffers caller buffers"
  written := lz4.compress(compressed[..], source) catch { #panic("unexpected failure") }
  decoded := lz4.decompress(output[..], compressed[..written]) catch { #panic("unexpected failure") }
  if !bytes.equal(output[..decoded], source) {
    #panic("LZ4 roundtrip")
  }
  if !rejected(false, output[..1], compressed[..written]) {
    #panic("short output accepted")
  }
  if !rejected(true, compressed[..0], source) {
    #panic("short compressed output accepted")
  }
  invalid: [1]u8 = [255]
  if !rejected(false, output[..], invalid[..]) {
    #panic("invalid block accepted")
  }
  empty := lz4.compress(compressed[..], "") catch { #panic("unexpected failure") }
  if (lz4.decompress(output[..0], compressed[..empty]) catch 1) != 0 {
    #panic("empty block")
  }
  if lz4.compress_bound(lz4.MaxInput + 1) != 0 {
    #panic("oversized input accepted")
  }
  io.println("LZ4 bounded roundtrip passed")
}
''',
    'cgltf': r'''use "vendor/cgltf"
use io "std/io"
use "std/bytes"
use "std/mem"
use "std/fs"
use "std/os/linux"
fn parses(text: []const u8) bool {
  model := cgltf.parse_owned(text) catch { return false }
  cgltf.destroy_owned(model)
  return true
}
fn normal_missing(model: cgltf.Model) bool {
  _ = cgltf.attribute(model, 0, 0, cgltf.Normal, 0) catch err {
    case err {
      .NotFound => { return true }
      _ => { return false }
    }
  }
  return false
}
fn no_color(model: cgltf.Model, material: usize) bool {
  _ = cgltf.base_color(model, material) catch { return true }
  return false
}
fn main() {
  document := "{\"asset\":{\"version\":\"2.0\"},\"nodes\":[{}],\"buffers\":[{\"byteLength\":12,\"uri\":\"data:application/octet-stream;base64,AAAAAAAAgD8AAABA\"}],\"bufferViews\":[{\"buffer\":0,\"byteLength\":12}],\"accessors\":[{\"bufferView\":0,\"componentType\":5126,\"count\":1,\"type\":\"VEC3\"}]}"
  model := cgltf.parse_owned(document) catch { #panic("unexpected failure") }
  defer cgltf.destroy_owned(model)
  cgltf.validate(model) catch { #panic("unexpected failure") }
  cgltf.load_embedded(model) catch { #panic("unexpected failure") }
  if cgltf.node_count(model) != 1 {
    #panic("glTF validate/load")
  }
  values: [3]f32
  cgltf.read_float(model, 0, 0, values[..]) catch { #panic("unexpected failure") }
  if values[0] != 0.0 || values[1] != 1.0 || values[2] != 2.0 {
    #panic("glTF accessor")
  }
  missing_accessor := false
  cgltf.read_float(model, 1, 0, values[..]) catch { missing_accessor = true }
  short_output := false
  cgltf.read_float(model, 0, 0, values[..1]) catch { short_output = true }
  if !missing_accessor || !short_output {
    #panic("glTF invalid accessor accepted")
  }
  if parses("broken") {
    #panic("invalid glTF accepted")
  }
  external := cgltf.parse_owned("{\"asset\":{\"version\":\"2.0\"},\"buffers\":[{\"byteLength\":12,\"uri\":\"external.bin\"}]}") catch { #panic("unexpected failure") }
  defer cgltf.destroy_owned(external)
  unattached := false
  cgltf.load_embedded(external) catch { unattached = true }
  if !unattached {
    #panic("external resource not rejected")
  }
  // Application chooses how external URIs are resolved. This example supplies
  // caller-owned arrays; real tools can read files into a retained model arena.
  mesh := cgltf.parse_owned("{\"asset\":{\"version\":\"2.0\"},\"buffers\":[{\"byteLength\":36,\"uri\":\"vertices.bin\"},{\"byteLength\":6,\"uri\":\"indices.bin\"}],\"bufferViews\":[{\"buffer\":0,\"byteLength\":36},{\"buffer\":1,\"byteLength\":6}],\"accessors\":[{\"bufferView\":0,\"componentType\":5126,\"count\":3,\"type\":\"VEC3\"},{\"bufferView\":1,\"componentType\":5123,\"count\":3,\"type\":\"SCALAR\"}],\"materials\":[{\"pbrMetallicRoughness\":{\"baseColorFactor\":[1,0.5,0.25,1]}}],\"meshes\":[{\"primitives\":[{\"attributes\":{\"POSITION\":0},\"indices\":1,\"material\":0}]}],\"nodes\":[{\"mesh\":0,\"translation\":[1,2,3]}]}") catch { #panic("unexpected failure") }
  defer cgltf.destroy_owned(mesh)
  vertices: [9]f32
  triangles: [3]u16
  triangles[1] = 1
  triangles[2] = 2
  vertex_bytes := #slice(#cast(*const u8, &vertices[0]), 36)
  index_bytes := #slice(#cast(*const u8, &triangles[0]), 6)
  short_buffer := false
  cgltf.attach_buffer(mesh, 0, vertex_bytes[..1]) catch { short_buffer = true }
  if cgltf.buffer_count(mesh) != 2 || !bytes.equal(cgltf.buffer_uri(mesh, 0, 256), "vertices.bin") || cgltf.buffer_size(mesh, 0) != 36 || !short_buffer {
    #panic("mesh resource metadata")
  }
  cgltf.attach_buffer(mesh, 0, vertex_bytes) catch { #panic("unexpected failure") }
  cgltf.attach_buffer(mesh, 1, index_bytes) catch { #panic("unexpected failure") }
  twice := false
  cgltf.attach_buffer(mesh, 0, vertex_bytes) catch { twice = true }
  if !twice {
    #panic("mesh buffer attachment")
  }
  cgltf.load_embedded(mesh) catch { #panic("unexpected failure") }
  cgltf.validate(mesh) catch { #panic("unexpected failure") }
  position := cgltf.attribute(mesh, 0, 0, cgltf.Position, 0) catch { #panic("unexpected failure") }
  indices := cgltf.indices(mesh, 0, 0) catch { #panic("unexpected failure") }
  material := cgltf.material(mesh, 0, 0) catch { #panic("unexpected failure") }
  node_mesh := cgltf.node_mesh(mesh, 0) catch { #panic("unexpected failure") }
  if cgltf.mesh_count(mesh) != 1 || cgltf.primitive_count(mesh, 0) != 1 || cgltf.material_count(mesh) != 1 || position != 0 || indices != 1 || material != 0 || cgltf.topology(mesh, 0, 0) != cgltf.Triangles || node_mesh != 0 || cgltf.element_count(mesh, 0) != 3 {
    #panic("mesh traversal")
  }
  past := (cgltf.read_index(mesh, 1, 3) catch 999) == 999
  if (cgltf.read_index(mesh, 1, 2) catch 0) != 2 || !past || !normal_missing(mesh) {
    #panic("mesh indices")
  }
  transform := cgltf.world_transform(mesh, 0) catch { #panic("unexpected failure") }
  color := cgltf.base_color(mesh, 0) catch { #panic("unexpected failure") }
  if transform[12] != 1.0 || transform[13] != 2.0 || transform[14] != 3.0 || color[1] != 0.5 || !no_color(mesh, 1) {
    #panic("mesh transform/material")
  }
  backing := mem.arena_alloc(2 * 1024 * 1024)
  defer {
    mem.arena_release(backing)
  }
  args := linux.process_arguments(backing)
  if args.len == 2 {
    file := fs.read_all(backing, args[1], 1024 * 1024) catch { #panic("cannot read a fixture") }
    binary := cgltf.parse_owned(file) catch { #panic("unexpected failure") }
    defer cgltf.destroy_owned(binary)
    cgltf.load_embedded(binary) catch { #panic("unexpected failure") }
    cgltf.read_float(binary, 0, 0, values[..]) catch { #panic("unexpected failure") }
    if values[2] != 2.0 {
      #panic("GLB accessor")
    }
  }
  io.println("cgltf embedded accessor passed")
}
''',
    'box2d': r'''use physics "vendor/box2d"
use "std/io"
fn stale(body: physics.Body) bool {
  _ = physics.position(body) catch { return true }
  return false
}
fn box_fails(body: physics.Body, half: f32) bool {
  _ = physics.box_create(body, half, 1.0, 1.0) catch { return true }
  return false
}
fn circle_fails(body: physics.Body, radius: f32) bool {
  _ = physics.circle_create(body, radius, 1.0) catch { return true }
  return false
}
fn joint_fails(first: physics.Body, second: physics.Body) bool {
  _ = physics.distance_joint(first, second, 2.0) catch { return true }
  return false
}
fn query_fails(world: physics.World, hits: []physics.Shape) bool {
  _ = physics.query(world, 2.0, 2.0, -2.0, -2.0, hits) catch { return true }
  return false
}
fn contact_missing(world: physics.World, index: usize) bool {
  _ = physics.contact(world, true, index) catch err {
    case err {
      .NotFound => { return true }
      _ => { return false }
    }
  }
  return false
}
fn main() {
  world := physics.create_owned(0.0, -10.0) catch { #panic("unexpected failure") }
  defer physics.destroy_owned(world)
  ground := physics.body_create(world, 0.0, -1.0, false) catch { #panic("unexpected failure") }
  falling := physics.body_create(world, 0.0, 4.0, true) catch { #panic("unexpected failure") }
  _ = physics.box_create(ground, 10.0, 1.0, 0.0) catch { #panic("unexpected failure") }
  _ = physics.box_create(falling, 0.5, 0.5, 1.0) catch { #panic("unexpected failure") }
  bad_step := false
  physics.step(world, -1.0, 4) catch { bad_step = true }
  if !bad_step || !box_fails(falling, -1.0) {
    #panic("invalid physics input")
  }
  circle_body := physics.body_create(world, 3.0, 4.0, true) catch { #panic("unexpected failure") }
  circle := physics.circle_create(circle_body, 0.5, 1.0) catch { #panic("unexpected failure") }
  physics.contact_events(circle, true) catch { #panic("unexpected failure") }
  if !circle_fails(circle_body, -1.0) {
    #panic("circle shape")
  }
  anchor := physics.body_create(world, 20.0, 4.0, false) catch { #panic("unexpected failure") }
  pendulum := physics.body_create(world, 20.0, 2.0, true) catch { #panic("unexpected failure") }
  _ = physics.circle_create(pendulum, 0.5, 1.0) catch { #panic("unexpected failure") }
  joint := physics.distance_joint(anchor, pendulum, 2.0) catch { #panic("unexpected failure") }
  if !joint_fails(anchor, anchor) {
    #panic("distance joint")
  }
  contacts := false
  for i in 0..240 {
    physics.step(world, 1.0 / 60.0, 4) catch { #panic("unexpected failure") }
    count := physics.contact_count(world, true) catch { #panic("unexpected failure") }
    for event_index in 0..count {
      event := physics.contact(world, true, event_index) catch { #panic("unexpected failure") }
      if event.first == circle || event.second == circle {
        contacts = true
      }
    }
  }
  circle_position := physics.position(circle_body) catch { #panic("unexpected failure") }
  joint_position := physics.position(pendulum) catch { #panic("unexpected failure") }
  if !contacts || circle_position.y < 0.4 || circle_position.y > 0.7 || joint_position.y < 1.9 || joint_position.y > 2.1 {
    #panic("circle contact/joint motion")
  }
  hits: [1]physics.Shape
  candidates := physics.query(world, -2.0, -2.0, 5.0, 5.0, hits[..]) catch { #panic("unexpected failure") }
  if candidates.total < 3 || candidates.written != 1 || !query_fails(world, hits[..]) || !contact_missing(world, 999) {
    #panic("physics query")
  }
  physics.joint_destroy(joint)
  physics.joint_destroy(joint)
  final := physics.position(falling) catch { #panic("unexpected failure") }
  if final.y < 0.4 || final.y > 0.7 {
    #panic("body failed to rest on ground")
  }
  physics.body_destroy(falling)
  if !stale(falling) {
    #panic("stale body ID")
  }
  physics.body_destroy(falling)
  io.println("Box2D falling box passed")
}
''',
    'microui': r'''use ui "vendor/microui"
use "std/mem"
use io "std/io"
use "std/bytes"
fn rejected(step: fn(ui.Context) !io.IoErr, context: ui.Context) bool {
  step(context) catch { return true }
  return false
}
fn outside_label(context: ui.Context) !io.IoErr {
  buffer: [64]u8
  try ui.label(context, "outside frame", buffer[..])
}
fn main() {
  storage := mem.arena_alloc(1024 * 1024)
  defer {
    mem.arena_release(storage)
  }
  context := ui.create(storage) catch { #panic("unexpected failure") }
  buffer: [256]u8
  if !rejected(outside_label, context) || !rejected(ui.end, context) {
    #panic("invalid UI state accepted")
  }
  frame: usize = 0
  for frame < 3 {
    ui.begin(context) catch { #panic("unexpected failure") }
    if !rejected(ui.begin, context) {
      #panic("UI frame")
    }
    if !(ui.window(context, "Debug", buffer[..], ui.Rectangle{ x: 10, y: 10, width: 300, height: 200 }) catch false) {
      #panic("UI window")
    }
    ui.label(context, "arena backed", buffer[..]) catch { #panic("unexpected failure") }
    _ = ui.button(context, "Button", buffer[..]) catch { #panic("unexpected failure") }
    if !rejected(ui.end, context) {
      #panic("UI balance")
    }
    ui.window_end(context) catch { #panic("unexpected failure") }
    ui.end(context) catch { #panic("unexpected failure") }
    texts: usize = 0
    rectangles: usize = 0
    for {
      command := ui.next(context)
      if command == nil {
        break
      }
      if ui.kind(command) == ui.Text && bytes.equal(ui.text(command), "arena backed") {
        texts += 1
      }
      if ui.kind(command) == ui.Rect {
        rectangles += 1
      }
    }
    if ui.next(context) != nil {
      #panic("UI exhausted iterator")
    }
    if texts == 0 || rectangles == 0 {
      #panic("UI draw commands")
    }
    frame += 1
  }
  io.println("microui arena draw commands passed")
}
''',
    'enet': r'''use "vendor/enet"
use "std/time"
use io "std/io"
use "std/bytes"
fn client_fails(peers: usize, channels: usize) bool {
  host := enet.client_channels_owned(peers, channels) catch { return true }
  enet.destroy_owned(host)
  return false
}
fn listen_fails(ip: []const u8, buffer: []u8) bool {
  host := enet.listen_at_owned(ip, 0, 1, 1, buffer) catch { return true }
  enet.destroy_owned(host)
  return false
}
fn main() {
  enet.init() catch { #panic("unexpected failure") }
  defer enet.quit()
  path: [64]u8
  server := enet.listen_at_owned("0.0.0.0", 0, 2, 2, path[..]) catch { #panic("unexpected failure") }
  defer enet.destroy_owned(server)
  client := enet.client_channels_owned(1, 2) catch { #panic("unexpected failure") }
  defer enet.destroy_owned(client)
  peer := enet.connect_channels(client, "127.0.0.1", enet.port(server), 2, path[..]) catch { #panic("unexpected failure") }
  no_peer := false
  enet.send(nil, "bad") catch { no_peer = true }
  if !no_peer || !client_fails(0, 1) {
    #panic("invalid ENet state accepted")
  }
  deadline := time.deadline_after(5 * time.Second)
  done := false
  for !done {
    if time.deadline_expired(&deadline) { break }
    remote := enet.service(server, 0) catch { #panic("unexpected failure") }
    if remote.kind == enet.Received {
      if remote.channel != 1 || !bytes.equal(enet.packet_bytes(remote.packet), "ping") {
        #panic("server payload")
      }
      enet.send_channel(remote.peer, 1, "pong") catch { #panic("unexpected failure") }
      enet.packet_destroy(remote.packet)
    }
    local := enet.service(client, 0) catch { #panic("unexpected failure") }
    if local.kind == enet.Connected {
      enet.send_channel(peer, 1, "ping") catch { #panic("unexpected failure") }
    }
    if local.kind == enet.Received {
      if local.channel != 1 || !bytes.equal(enet.packet_bytes(local.packet), "pong") {
        #panic("client payload")
      }
      enet.packet_destroy(local.packet)
      done = true
    }
    time.sleep(time.Millisecond)
  }
  if !done {
    #panic("ENet loopback timed out")
  }
  bad_channel := false
  enet.send_channel(peer, 2, "invalid") catch { bad_channel = true }
  if !bad_channel || !client_fails(1, 256) || !listen_fails("bad address", path[..]) {
    #panic("invalid ENet configuration")
  }
  enet.disconnect_with_reason(peer, 42)
  server_closed := false
  client_closed := false
  deadline = time.deadline_after(5 * time.Second)
  for (!server_closed || !client_closed) {
    if time.deadline_expired(&deadline) { break }
    server_event := enet.service(server, 0) catch { #panic("unexpected failure") }
    client_event := enet.service(client, 0) catch { #panic("unexpected failure") }
    if server_event.kind == enet.Disconnected {
      if server_event.data != 42 {
        #panic("disconnect reason")
      }
      server_closed = true
    }
    if client_event.kind == enet.Disconnected {
      client_closed = true
    }
    if server_event.kind == enet.Received {
      enet.packet_destroy(server_event.packet)
    }
    if client_event.kind == enet.Received {
      enet.packet_destroy(client_event.packet)
    }
    time.sleep(time.Millisecond)
  }
  if !server_closed || !client_closed {
    #panic("disconnect deadline")
  }
  io.println("ENet reliable loopback passed")
}
''',
    'miniaudio': r'''use audio "vendor/miniaudio"
use "std/mem"
use "std/os/linux"
use "std/fs"
use "std/io"
use "std/time"
fn read_fails(decoder: rawptr, output: []f32) bool {
  _ = audio.decoder_read(decoder, output) catch { return true }
  return false
}
fn main() {
  storage := mem.arena_alloc(4 * 1024 * 1024)
  defer {
    mem.arena_release(storage)
  }
  args := linux.process_arguments(storage)
  if args.len != 2 {
    #panic("WAV path required")
  }
  bytes := fs.read_all(storage, args[1], 1024 * 1024) catch { #panic("cannot read a fixture") }
  mark := mem.arena_mark(storage)
  if (audio.decoder_create(storage, "invalid") catch nil) != nil || mem.arena_mark(storage) != mark {
    #panic("invalid decoder rollback")
  }
  decoder := audio.decoder_create(storage, bytes) catch { #panic("unexpected failure") }
  defer audio.decoder_close(decoder)
  samples: [2048]f32
  heard := false
  ended := false
  iterations: usize = 0
  for iterations < 200 {
    result := audio.decoder_read(decoder, samples[..]) catch { #panic("unexpected failure") }
    for sample in samples[..result.samples] {
      if sample != 0.0 {
        heard = true
      }
    }
    if result.ended || result.samples == 0 {
      ended = true
      break
    }
    iterations += 1
  }
  if !heard || !ended || !read_fails(decoder, samples[..1]) {
    #panic("decode frames")
  }
  audio.decoder_close(decoder)
  if !read_fails(decoder, samples[..]) {
    #panic("closed decoder accepted")
  }
  engine := audio.engine_create(storage, false) catch { #panic("unexpected failure") }
  defer audio.engine_close(engine)
  path: [4096]u8
  audio.play_file(engine, args[1], path[..]) catch { #panic("unexpected failure") }
  heard = false
  iterations = 0
  for !heard && iterations < 200 {
    count := audio.mix(engine, samples[..]) catch { #panic("unexpected failure") }
    for mixed_sample in samples[..count] {
      if mixed_sample != 0.0 {
        heard = true
      }
    }
    if !heard {
      time.sleep(time.Millisecond)
    }
    iterations += 1
  }
  if !heard {
    #panic("engine produced no audio")
  }
  io.println("miniaudio decode and offline mixing passed")
}
''',
    'sdl3-mixer': r'''use "vendor/sdl3/mixer"
use "std/mem"
use "std/os/linux"
use "std/fs"
use "std/io"
fn generate_fails(engine: mixer.Mixer, samples: []f32) bool {
  _ = mixer.generate(engine, samples) catch { return true }
  return false
}
fn main() {
  storage := mem.arena_alloc(4 * 1024 * 1024)
  defer {
    mem.arena_release(storage)
  }
  args := linux.process_arguments(storage)
  if args.len != 2 {
    #panic("WAV path required")
  }
  bytes := fs.read_all(storage, args[1], 1024 * 1024) catch { #panic("cannot read a fixture") }
  mixer.init() catch { #panic("unexpected failure") }
  defer mixer.quit()
  engine := mixer.create_owned() catch { #panic("unexpected failure") }
  defer mixer.destroy_owned(engine)
  audio := mixer.decode_owned(engine, bytes) catch { #panic("unexpected failure") }
  defer mixer.audio_destroy_owned(audio)
  if (mixer.decode_owned(engine, "invalid") catch nil) != nil {
    #panic("invalid audio accepted")
  }
  track := mixer.track_create(engine) catch { #panic("unexpected failure") }
  defer mixer.track_destroy(track)
  mixer.play(track, audio) catch { #panic("unexpected failure") }
  samples: [2048]f32
  heard := false
  iterations: usize = 0
  for iterations < 200 && mixer.playing(track) {
    written := mixer.generate(engine, samples[..]) catch { #panic("unexpected failure") }
    for sample in samples[..written] {
      if sample != 0.0 {
        heard = true
      }
    }
    iterations += 1
  }
  if !heard || mixer.playing(track) {
    #panic("mixer did not finish audio")
  }
  mixer.play(track, audio) catch { #panic("unexpected failure") }
  mixer.stop(track) catch { #panic("unexpected failure") }
  if mixer.playing(track) {
    #panic("mixer stop")
  }
  if (mixer.generate(engine, samples[..]) catch 1) != 0 {
    #panic("mixer silence status")
  }
  for silent_sample in samples {
    if silent_sample != 0.0 {
      #panic("mixer silence output")
    }
  }
  if !generate_fails(engine, samples[..1]) {
    #panic("odd sample count accepted")
  }
  device := mixer.create_device_owned() catch { #panic("unexpected failure") }
  defer mixer.destroy_owned(device)
  io.println("SDL_mixer offline playback passed")
}
''',
}
ORACLES = {
    'stb': r'''#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stddef.h>
#include <string.h>
typedef struct { int32_t width,height,x,y,packed; } Rectangle;
extern size_t dyn_stb_pack_size(int,size_t);
extern int dyn_stb_pack(int,int,Rectangle*,size_t,void*,size_t);
extern bool dyn_stb_resize(const void*,size_t,int,int,void*,size_t,int,int,int,bool,void*,void *(*)(void*,size_t));
typedef struct { unsigned char *data;size_t size,used; } Arena;
static void *allocate(void *context,size_t size) {
    Arena *a=context;size_t offset=(a->used+63)&~(size_t)63;
    if (offset>a->size || size>a->size-offset) return NULL;
    a->used=offset+size;return a->data+offset;
}
static uint32_t seed=1234567;
static unsigned random_value(void) { seed=seed*1664525+1013904223;return seed; }
int main(void) {
    _Alignas(64) unsigned char scratch[1024*1024];
    Rectangle rects[64];
    for (int pass=0;pass<100;pass++) {
        for (int i=0;i<64;i++) rects[i]=(Rectangle){.width=1+(int)(random_value()%16),.height=1+(int)(random_value()%16)};
        assert(dyn_stb_pack_size(64,64)<=sizeof(scratch));
        int result=dyn_stb_pack(64,64,rects,64,scratch,sizeof(scratch));assert(result>=0);
        for (int i=0;i<64;i++) if (rects[i].packed) {
            Rectangle a=rects[i];assert(a.x>=0 && a.y>=0 && a.x+a.width<=64 && a.y+a.height<=64);
            for (int j=i+1;j<64;j++) if (rects[j].packed) {
                Rectangle b=rects[j];assert(a.x+a.width<=b.x || b.x+b.width<=a.x || a.y+a.height<=b.y || b.y+b.height<=a.y);
            }
        }
    }
    unsigned char input[16*16*4],output[32*32*4];memset(input,127,sizeof(input));
    for (int channels=1;channels<=4;channels++) for (int srgb=0;srgb<=1;srgb++) for (int width=1;width<=32;width*=2) {
        Arena arena={scratch,1,0};
        assert(!dyn_stb_resize(input,sizeof(input),16,16,output,sizeof(output),width,width,channels,srgb,&arena,allocate));
        arena=(Arena){scratch,sizeof(scratch),0};
        assert(dyn_stb_resize(input,sizeof(input),16,16,output,sizeof(output),width,width,channels,srgb,&arena,allocate));
        for (int i=0;i<width*width*channels;i++) assert(output[i]>=126 && output[i]<=128);
    }
    Arena invalid={scratch,sizeof(scratch),0};
    assert(!dyn_stb_resize(input,sizeof(input),32768,32768,output,sizeof(output),1,1,4,false,&invalid,allocate));
    assert(invalid.used==0);
    assert(!dyn_stb_pack_size(0,64));
    puts("PASS stb randomized non-overlap, channel/color-space resizes and short scratch");
}
''',
    'ui': r'''/* Native renderer oracle: real software pixels, SDL event ABI, restored state. */
#include <SDL3/SDL.h>
#include <assert.h>
#include <math.h>
#include <stddef.h>
#include <stdio.h>
extern size_t dyn_mu_size(void);
extern void dyn_mu_init(void*);
extern bool dyn_mu_begin(void*);
extern bool dyn_mu_end(void*);
extern bool dyn_mu_window(void*,const char*,int,int,int,int);
extern bool dyn_mu_window_end(void*);
extern int dyn_mu_button(void*,const char*);
extern bool dyn_mu_sdl_event(void*,SDL_Renderer*,const SDL_Event*);
extern bool dyn_mu_sdl_render(void*,SDL_Renderer*);
int main(void) {
    assert(SDL_Init(SDL_INIT_VIDEO));
    SDL_Surface *surface=SDL_CreateSurface(320,240,SDL_PIXELFORMAT_RGBA32);assert(surface);
    SDL_Renderer *renderer=SDL_CreateSoftwareRenderer(surface);assert(renderer);
    max_align_t state[(dyn_mu_size()+sizeof(max_align_t)-1)/sizeof(max_align_t)];
    dyn_mu_init(state);assert(!dyn_mu_sdl_render(state,renderer));
    SDL_Rect clip={1,2,3,4};
    SDL_Event event={0};event.type=SDL_EVENT_MOUSE_MOTION;event.motion.x=60;event.motion.y=55;
    bool clicked=false;
    for (int frame=0;frame<4;frame++) {
        event.type=SDL_EVENT_MOUSE_MOTION;event.motion.x=60;event.motion.y=55;
        assert(dyn_mu_sdl_event(state,renderer,&event));
        if (frame==2 || frame==3) {
            event.type=frame==2?SDL_EVENT_MOUSE_BUTTON_DOWN:SDL_EVENT_MOUSE_BUTTON_UP;
            event.button.button=SDL_BUTTON_LEFT;event.button.x=60;event.button.y=55;
            assert(dyn_mu_sdl_event(state,renderer,&event));
        }
        assert(dyn_mu_begin(state));assert(!dyn_mu_sdl_render(state,renderer));
        assert(dyn_mu_window(state,"Panel",10,10,250,200));
        if (dyn_mu_button(state,"Click")==1) clicked=true;
        assert(dyn_mu_window_end(state));assert(dyn_mu_end(state));
        assert(SDL_SetRenderClipRect(renderer,NULL));
        assert(SDL_SetRenderDrawColor(renderer,0,0,0,255));assert(SDL_RenderClear(renderer));
        assert(SDL_SetRenderClipRect(renderer,&clip));
        assert(SDL_SetRenderDrawBlendMode(renderer,SDL_BLENDMODE_NONE));
        assert(SDL_SetRenderDrawColorFloat(renderer,0.125f,0.25f,0.375f,0.5f));
        assert(dyn_mu_sdl_render(state,renderer));assert(SDL_RenderPresent(renderer));
        Uint8 r,g,b,a;SDL_Rect actual;SDL_BlendMode mode;
        assert(SDL_RenderClipEnabled(renderer));assert(SDL_GetRenderClipRect(renderer,&actual));
        assert(actual.x==1 && actual.y==2 && actual.w==3 && actual.h==4);
        assert(SDL_GetRenderDrawBlendMode(renderer,&mode) && mode==SDL_BLENDMODE_NONE);
        float rf,gf,bf,af;
        assert(SDL_GetRenderDrawColorFloat(renderer,&rf,&gf,&bf,&af) && rf==0.125f && gf==0.25f && bf==0.375f && af==0.5f);
        assert(SDL_ReadSurfacePixel(surface,20,100,&r,&g,&b,&a) && (r || g || b));
        assert(SDL_ReadSurfacePixel(surface,300,230,&r,&g,&b,&a) && r==0 && g==0 && b==0);
    }
    assert(clicked);
    event.type=SDL_EVENT_MOUSE_MOTION;event.motion.x=INFINITY;
    assert(!dyn_mu_sdl_event(state,renderer,&event));
    SDL_DestroyRenderer(renderer);SDL_DestroySurface(surface);SDL_Quit();
    puts("PASS SDL UI pixels, input, invalid state and renderer restoration");
}
''',
}

rows=[]
with tempfile.TemporaryDirectory(prefix='dyn-extra-vendors-') as directory:
 work=Path(directory);wav=work/'tone.wav'
 with wave.open(str(wav),'wb') as out:
  out.setnchannels(1);out.setsampwidth(2);out.setframerate(8000)
  out.writeframes(b''.join(struct.pack('<h',4000 if i%20<10 else -4000) for i in range(800)))
 glb=work/'triangle.glb'
 document={'asset':{'version':'2.0'},'buffers':[{'byteLength':12}],'bufferViews':[{'buffer':0,'byteLength':12}],'accessors':[{'bufferView':0,'componentType':5126,'count':1,'type':'VEC3'}]}
 encoded=json.dumps(document,separators=(',',':')).encode();encoded+=b' '*((-len(encoded))%4)
 binary=struct.pack('<fff',0,1,2)
 chunks=struct.pack('<II',len(encoded),0x4e4f534a)+encoded+struct.pack('<II',len(binary),0x004e4942)+binary
 glb.write_bytes(struct.pack('<III',0x46546c67,2,12+len(chunks))+chunks)
 cases=[('stb','dyn-stb','stb atlas and resize',[]),('microui-sdl3','dyn-microui-sdl3','microui SDL rendering',['--smoke']),('audio-playback','dyn-miniaudio','audio playback completion',[str(wav),'--offline']),('lz4','liblz4','bounded roundtrip',[]),('cgltf','dyn-cgltf','embedded accessor',[str(glb)]),('box2d','dyn-box2d','falling box',[]),('microui','dyn-microui','arena draw commands',[]),('enet','dyn-enet','reliable loopback',[]),('miniaudio','dyn-miniaudio','offline mixing',[str(wav)]),('sdl3-mixer','sdl3-mixer','offline playback',[str(wav)])]
 if a.providers:
  unknown=set(a.providers)-{row[0] for row in cases}
  if unknown:p.error('Unknown providers: '+', '.join(sorted(unknown)))
  cases=[row for row in cases if row[0] in a.providers]
 try:
  for name,package,expected,args in cases:
   if subprocess.run(['pkg-config','--exists',package],env=env).returncode:
    raise RuntimeError('Missing required provider '+package)
   project=work/(name+'-source');project.mkdir()
   (project/'main.dyn').write_text(FIXTURES[name])
   version=subprocess.check_output(['pkg-config','--modversion',package],env=env,text=True).strip()
   for release in (False,True):
    binary=work/name
    subprocess.run([dyn,'build',str(project),'--quiet','--no-cache','--output',str(binary)]+(['--release'] if release else []),env=env,check=True,timeout=120)
    result=subprocess.run([str(binary),*args],env=env,cwd=ROOT,capture_output=True,text=True,timeout=20)
    assert result.returncode==0 and expected in result.stdout,(name,release,result.returncode,result.stdout,result.stderr)
   if name=='stb':
    (work/'stb.c').write_text(ORACLES['stb'])
    oracle=work/'stb-oracle'
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','dyn-stb'],env=env,text=True))
    subprocess.run([*shlex.split(env.get('CC','cc')),'-std=c11','-Wall','-Wextra','-Werror',str(work/'stb.c'),*flags,'-o',str(oracle)],env=env,check=True,timeout=60)
    subprocess.run([str(oracle)],env=env,check=True,timeout=20)
   if name=='microui-sdl3':
    (work/'ui.c').write_text(ORACLES['ui'])
    oracle=work/'ui-oracle'
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','sdl3','dyn-microui','dyn-microui-sdl3'],env=env,text=True))
    subprocess.run([*shlex.split(env.get('CC','cc')),'-std=c11','-Wall','-Wextra','-Werror',str(work/'ui.c'),*flags,'-o',str(oracle)],env=env,check=True,timeout=60)
    subprocess.run([str(oracle)],env=env,check=True,timeout=20)
   rows.append(dict(package=name,status='passed',version=version,modes=['debug','release']))
   print('PASS '+name+' provider metadata '+version+' native debug/release',flush=True)
 except BaseException as error:rows.append(dict(status='failed',error=str(error)));raise
 finally:
  BUILD.mkdir(parents=True,exist_ok=True)
  (BUILD/'vendor-extra-results.json').write_text(json.dumps(rows,indent=2)+'\n')
