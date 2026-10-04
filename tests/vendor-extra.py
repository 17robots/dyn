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
    'stb': r'''use "vendor/stb/rect_pack" atlas
use "vendor/stb/image_resize" image
use "std/mem"
use "std/io"
fn main() {
  backing := mem.arena_create(2 * 1024 * 1024)
  if !backing.ok {
    #panic("asset arena")
  }
  defer {
    _ = mem.arena_release(&backing.arena)
  }
  rectangles: [3]atlas.Rectangle = []
  rectangles[0] = atlas.Rectangle{ width: 8, height: 8 }
  rectangles[1] = atlas.Rectangle{ width: 4, height: 4 }
  rectangles[2] = atlas.Rectangle{ width: 4, height: 4 }
  mark := mem.arena_mark(&backing.arena)
  packed := atlas.pack(&backing.arena, 16, 16, rectangles[..])
  if !packed.ok || packed.packed != 3 || mem.arena_mark(&backing.arena) != mark {
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
  partial := atlas.pack(&backing.arena, 4, 4, rectangles[..])
  if partial.ok || partial.code != 0 || partial.packed != 1 {
    #panic("atlas partial fit")
  }
  rectangles[0].width = -1
  if atlas.pack(&backing.arena, 16, 16, rectangles[..]).code != -1 {
    #panic("invalid atlas rectangle")
  }
  source: [16]u8 = []
  destination: [64]u8 = []
  k: usize = 0
  for k < 16 {
    source[k] = 128
    k += 1
  }
  if !image.resize(&backing.arena, source[..], 2, 2, destination[..], 4, 4, 4, false) {
    #panic("resize")
  }
  for value in destination[..] {
    if value != 128 {
      #panic("resize constant color")
    }
  }
  if !image.resize(&backing.arena, source[..], 2, 2, destination[..], 4, 4, 4, true) {
    #panic("sRGB resize")
  }
  if image.resize(&backing.arena, source[..], 2, 2, destination[..1], 4, 4, 4, false) || image.resize(&backing.arena, source[..], 2, 2, source[..], 2, 2, 4, false) || image.resize(&backing.arena, source[..], 0, 2, destination[..], 4, 4, 4, false) {
    #panic("resize bounds")
  }
  if mem.arena_mark(&backing.arena) != mark {
    #panic("scratch leak")
  }
  tiny: [1]u8 = []
  short_arena := mem.arena_from_buffer(tiny[..])
  if image.resize(&short_arena, source[..], 2, 2, destination[..], 4, 4, 4, false) || mem.arena_mark(&short_arena) != 0 || atlas.pack(&short_arena, 16, 16, rectangles[..]).code != -1 || mem.arena_mark(&short_arena) != 0 {
    #panic("short scratch arena")
  }
  _ = io.println(io.stdout(), "stb atlas and resize passed")
}
''',
    'microui-sdl3': r'''use "vendor/microui" ui
use "vendor/sdl3" sdl
use "vendor/sdl3/microui" backend
use "std/mem"
use "std/os/linux"
use "std/strings"
use "std/time"
use "std/io"
fn main() {
  arena := mem.arena_create(1024 * 1024)
  if !arena.ok {
    #panic("UI arena")
  }
  defer {
    _ = mem.arena_release(&arena.arena)
  }
  args := linux.process_arguments(&arena.arena)
  smoke := #len(args) == 2 && strings.equal(args[1], "--smoke")
  if !sdl.init_video() {
    #panic("SDL video")
  }
  defer sdl.quit()
  text: [256]u8 = []
  window := sdl.window_create("Dyn interactive UI", text[..], 640, 360, sdl.WindowResizable)
  if !window.ok {
    #panic("SDL window")
  }
  defer sdl.window_destroy_owned(window.value)
  renderer := sdl.renderer_create_default_owned(window.value)
  if !renderer.ok {
    #panic("SDL renderer")
  }
  defer sdl.renderer_destroy_owned(renderer.value)
  context := ui.create(&arena.arena)
  if context == nil {
    #panic("UI context")
  }
  running := true
  clicked := false
  frame: usize = 0
  event := sdl.Event{}
  for running {
    for sdl.poll_event(&event) {
      if sdl.event_requests_close(&event) {
        running = false
      }
      _ = backend.event(context, renderer.value, &event)
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
    if !ui.begin(context) {
      #panic("UI begin")
    }
    if ui.window(context, "Debug panel", text[..], ui.Rectangle{ x: 20, y: 20, width: 300, height: 220 }) {
      if clicked {
        _ = ui.label(context, "Button clicked!", text[..])
      }
      else {
        _ = ui.label(context, "Click the button below", text[..])
      }
      if ui.button(context, "Click me", text[..]) == 1 {
        clicked = true
      }
      _ = ui.window_end(context)
    }
    if !ui.end(context) || !sdl.clear(renderer.value, 20, 28, 48, 255) || !backend.render(context, renderer.value) || !sdl.present(renderer.value) {
      #panic("UI render")
    }
    frame += 1
    if smoke && frame >= 5 {
      break
    }
    _ = time.sleep(16 * time.Millisecond)
  }
  if smoke && !clicked {
    #panic("UI mouse click not delivered")
  }
  _ = io.println(io.stdout(), "microui SDL rendering passed")
}
''',
    'audio-playback': r'''use "vendor/miniaudio" audio
use "std/mem"
use "std/os/linux"
use "std/strings"
use "std/time"
use "std/io"
fn main() {
  arena := mem.arena_create(2 * 1024 * 1024)
  if !arena.ok {
    #panic("audio arena")
  }
  defer {
    _ = mem.arena_release(&arena.arena)
  }
  args := linux.process_arguments(&arena.arena)
  if #len(args) < 2 {
    #panic("usage: audio-playback-example FILE.wav [--offline]")
  }
  offline := #len(args) == 3 && strings.equal(args[2], "--offline")
  engine := audio.engine_create(&arena.arena, !offline)
  if !engine.ok {
    #panic("audio engine/device")
  }
  defer audio.engine_close(engine.value)
  path: [4096]u8 = []
  mark := mem.arena_mark(&arena.arena)
  if audio.sound_create(&arena.arena, engine.value, "/nonexistent/dyn-audio-fixture", path[..]).ok || mem.arena_mark(&arena.arena) != mark {
    #panic("sound failure rollback")
  }
  sound := audio.sound_create(&arena.arena, engine.value, args[1], path[..])
  if !sound.ok {
    #panic("sound decode")
  }
  defer audio.sound_close(sound.value)
  if !audio.sound_volume(sound.value, 0.5) || audio.sound_volume(sound.value, -1.0) || audio.sound_start(sound.value) != 0 || audio.sound_stop(sound.value) != 0 || audio.sound_playing(sound.value) || audio.sound_rewind(sound.value) != 0 || audio.sound_start(sound.value) != 0 {
    #panic("sound controls")
  }
  deadline := time.deadline_after(60 * time.Second)
  samples: [2048]f32 = []
  heard := false
  for !audio.sound_ended(sound.value) && !time.deadline_expired(&deadline) {
    if offline {
      result := audio.mix(engine.value, samples[..])
      if !result.ok {
        #panic("audio mix")
      }
      for sample in samples[..result.samples] {
        if sample != 0.0 {
          heard = true
        }
      }
    } else {
      _ = time.sleep(10 * time.Millisecond)
    }
  }
  if !audio.sound_ended(sound.value) || (offline && !heard) {
    #panic("audio completion")
  }
  audio.sound_close(sound.value)
  if audio.sound_start(sound.value) == 0 {
    #panic("closed sound accepted")
  }
  _ = io.println(io.stdout(), "audio playback completion passed")
}
''',
    'lz4': r'''use "vendor/lz4"
use "std/strings"
use "std/io"
fn main() {
  compressed: [128]u8 = []
  output: [128]u8 = []
  source := "caller buffers caller buffers caller buffers"
  result := lz4.compress(compressed[..], source)
  if !result.ok {
    #panic("LZ4 compression")
  }
  decoded := lz4.decompress(output[..], compressed[..result.written])
  if !decoded.ok || !strings.equal(output[..decoded.written], source) {
    #panic("LZ4 roundtrip")
  }
  if lz4.decompress(output[..1], compressed[..result.written]).ok {
    #panic("short output accepted")
  }
  if lz4.compress(compressed[..0], source).ok {
    #panic("short compressed output accepted")
  }
  invalid: [1]u8 = [255]
  if lz4.decompress(output[..], invalid[..]).ok {
    #panic("invalid block accepted")
  }
  empty := lz4.compress(compressed[..], "")
  if !empty.ok || !lz4.decompress(output[..0], compressed[..empty.written]).ok {
    #panic("empty block")
  }
  if lz4.compress_bound(lz4.MaxInput + 1) != 0 {
    #panic("oversized input accepted")
  }
  _ = io.println(io.stdout(), "LZ4 bounded roundtrip passed")
}
''',
    'cgltf': r'''use "vendor/cgltf"
use "std/strings"
use "std/io"
use "std/mem"
use "std/fs"
use "std/os/linux"
fn main() {
  bytes := "{\"asset\":{\"version\":\"2.0\"},\"nodes\":[{}],\"buffers\":[{\"byteLength\":12,\"uri\":\"data:application/octet-stream;base64,AAAAAAAAgD8AAABA\"}],\"bufferViews\":[{\"buffer\":0,\"byteLength\":12}],\"accessors\":[{\"bufferView\":0,\"componentType\":5126,\"count\":1,\"type\":\"VEC3\"}]}"
  model := cgltf.parse_owned(bytes)
  if !model.ok {
    #panic("glTF parse")
  }
  defer cgltf.destroy_owned(model.value)
  if !cgltf.validate(model.value) || cgltf.load_embedded(model.value) != 0 || cgltf.node_count(model.value) != 1 {
    #panic("glTF validate/load")
  }
  values: [3]f32 = []
  if !cgltf.read_float(model.value, 0, 0, values[..]) || values[0] != 0.0 || values[1] != 1.0 || values[2] != 2.0 {
    #panic("glTF accessor")
  }
  if cgltf.read_float(model.value, 1, 0, values[..]) || cgltf.read_float(model.value, 0, 0, values[..1]) {
    #panic("glTF invalid accessor accepted")
  }
  if cgltf.parse_owned("broken").ok {
    #panic("invalid glTF accepted")
  }
  external := cgltf.parse_owned("{\"asset\":{\"version\":\"2.0\"},\"buffers\":[{\"byteLength\":12,\"uri\":\"external.bin\"}]}")
  if !external.ok {
    #panic("external glTF parse")
  }
  defer cgltf.destroy_owned(external.value)
  if cgltf.load_embedded(external.value) != -2 {
    #panic("external resource not rejected")
  }
  // Application chooses how external URIs are resolved. This example supplies
  // caller-owned arrays; real tools can read files into a retained model arena.
  mesh := cgltf.parse_owned("{\"asset\":{\"version\":\"2.0\"},\"buffers\":[{\"byteLength\":36,\"uri\":\"vertices.bin\"},{\"byteLength\":6,\"uri\":\"indices.bin\"}],\"bufferViews\":[{\"buffer\":0,\"byteLength\":36},{\"buffer\":1,\"byteLength\":6}],\"accessors\":[{\"bufferView\":0,\"componentType\":5126,\"count\":3,\"type\":\"VEC3\"},{\"bufferView\":1,\"componentType\":5123,\"count\":3,\"type\":\"SCALAR\"}],\"materials\":[{\"pbrMetallicRoughness\":{\"baseColorFactor\":[1,0.5,0.25,1]}}],\"meshes\":[{\"primitives\":[{\"attributes\":{\"POSITION\":0},\"indices\":1,\"material\":0}]}],\"nodes\":[{\"mesh\":0,\"translation\":[1,2,3]}]}")
  if !mesh.ok {
    #panic("mesh parse")
  }
  defer cgltf.destroy_owned(mesh.value)
  vertices: [9]f32 = []
  triangles: [3]u16 = []
  triangles[1] = 1
  triangles[2] = 2
  vertex_bytes := (#cast(*const u8) &vertices[0])[..36]
  index_bytes := (#cast(*const u8) &triangles[0])[..6]
  if cgltf.buffer_count(mesh.value) != 2 || !strings.equal(cgltf.buffer_uri(mesh.value, 0, 256), "vertices.bin") || cgltf.buffer_size(mesh.value, 0) != 36 || cgltf.attach_buffer(mesh.value, 0, vertex_bytes[..1]) {
    #panic("mesh resource metadata")
  }
  if !cgltf.attach_buffer(mesh.value, 0, vertex_bytes) || !cgltf.attach_buffer(mesh.value, 1, index_bytes) || cgltf.attach_buffer(mesh.value, 0, vertex_bytes) || cgltf.load_embedded(mesh.value) != 0 || !cgltf.validate(mesh.value) {
    #panic("mesh buffer attachment")
  }
  if cgltf.mesh_count(mesh.value) != 1 || cgltf.primitive_count(mesh.value, 0) != 1 || cgltf.material_count(mesh.value) != 1 || cgltf.attribute(mesh.value, 0, 0, cgltf.Position, 0) != 0 || cgltf.indices(mesh.value, 0, 0) != 1 || cgltf.material(mesh.value, 0, 0) != 0 || cgltf.topology(mesh.value, 0, 0) != cgltf.Triangles || cgltf.node_mesh(mesh.value, 0) != 0 || cgltf.element_count(mesh.value, 0) != 3 {
    #panic("mesh traversal")
  }
  index := cgltf.read_index(mesh.value, 1, 2)
  if !index.ok || index.value != 2 || cgltf.read_index(mesh.value, 1, 3).ok || cgltf.attribute(mesh.value, 0, 0, cgltf.Normal, 0) != -1 {
    #panic("mesh indices")
  }
  transform: [16]f32 = []
  color: [4]f32 = []
  if !cgltf.world_transform(mesh.value, 0, transform[..]) || transform[12] != 1.0 || transform[13] != 2.0 || transform[14] != 3.0 || !cgltf.base_color(mesh.value, 0, color[..]) || color[1] != 0.5 || cgltf.base_color(mesh.value, 1, color[..]) {
    #panic("mesh transform/material")
  }
  backing := mem.arena_create(2 * 1024 * 1024)
  if !backing.ok {
    #panic("glTF file arena")
  }
  defer {
    _ = mem.arena_release(&backing.arena)
  }
  args := linux.process_arguments(&backing.arena)
  if #len(args) == 2 {
    file := fs.read_all(&backing.arena, args[1], 1024 * 1024)
    if !file.ok {
      #panic("GLB read")
    }
    binary := cgltf.parse_owned(file.data)
    if !binary.ok {
      #panic("GLB parse")
    }
    defer cgltf.destroy_owned(binary.value)
    if cgltf.load_embedded(binary.value) != 0 || !cgltf.read_float(binary.value, 0, 0, values[..]) || values[2] != 2.0 {
      #panic("GLB accessor")
    }
  }
  _ = io.println(io.stdout(), "cgltf embedded accessor passed")
}
''',
    'box2d': r'''use "vendor/box2d" physics
use "std/io"
fn main() {
  world := physics.create_owned(0.0, -10.0)
  if world == 0 {
    #panic("physics world")
  }
  defer {
    _ = physics.destroy_owned(world)
  }
  ground := physics.body_create(world, 0.0, -1.0, false)
  falling := physics.body_create(world, 0.0, 4.0, true)
  if ground == 0 || falling == 0 || physics.box_create(ground, 10.0, 1.0, 0.0) == 0 || physics.box_create(falling, 0.5, 0.5, 1.0) == 0 {
    #panic("physics bodies")
  }
  if physics.step(world, -1.0, 4) || physics.box_create(falling, -1.0, 1.0, 1.0) != 0 {
    #panic("invalid physics input")
  }
  circle_body := physics.body_create(world, 3.0, 4.0, true)
  circle := physics.circle_create(circle_body, 0.5, 1.0)
  if circle == 0 || !physics.contact_events(circle, true) || physics.circle_create(circle_body, -1.0, 1.0) != 0 {
    #panic("circle shape")
  }
  anchor := physics.body_create(world, 20.0, 4.0, false)
  pendulum := physics.body_create(world, 20.0, 2.0, true)
  if physics.circle_create(pendulum, 0.5, 1.0) == 0 {
    #panic("joint shape")
  }
  joint := physics.distance_joint(anchor, pendulum, 2.0)
  if joint == 0 || physics.distance_joint(anchor, anchor, 2.0) != 0 {
    #panic("distance joint")
  }
  contacts := false
  i: usize = 0
  for i < 240 {
    if !physics.step(world, 1.0 / 60.0, 4) {
      #panic("physics step")
    }
    count := physics.contact_count(world, true)
    event_index: i32 = 0
    for event_index < count {
      event := physics.contact(world, true, event_index)
      if !event.ok {
        #panic("contact event")
      }
      if event.first == circle || event.second == circle {
        contacts = true
      }
      event_index += 1
    }
    i += 1
  }
  circle_position := physics.position(circle_body)
  joint_position := physics.position(pendulum)
  if !contacts || !circle_position.ok || circle_position.y < 0.4 || circle_position.y > 0.7 || !joint_position.ok || joint_position.y < 1.9 || joint_position.y > 2.1 {
    #panic("circle contact/joint motion")
  }
  hits: [1]physics.Shape = []
  candidates := physics.query(world, -2.0, -2.0, 5.0, 5.0, hits[..])
  if !candidates.ok || candidates.total < 3 || candidates.written != 1 || physics.query(world, 2.0, 2.0, -2.0, -2.0, hits[..]).ok || physics.contact(world, true, 999).ok {
    #panic("physics query")
  }
  if !physics.joint_destroy(joint) || physics.joint_destroy(joint) {
    #panic("joint destruction")
  }
  final := physics.position(falling)
  if !final.ok || final.y < 0.4 || final.y > 0.7 {
    #panic("body failed to rest on ground")
  }
  if !physics.body_destroy(falling) || physics.position(falling).ok || physics.body_destroy(falling) {
    #panic("stale body ID")
  }
  _ = io.println(io.stdout(), "Box2D falling box passed")
}
''',
    'microui': r'''use "vendor/microui" ui
use "std/mem"
use "std/strings"
use "std/io"
fn main() {
  storage := mem.arena_create(1024 * 1024)
  if !storage.ok {
    #panic("UI arena")
  }
  defer {
    _ = mem.arena_release(&storage.arena)
  }
  context := ui.create(&storage.arena)
  if context == nil {
    #panic("UI context")
  }
  buffer: [256]u8 = []
  if ui.label(context, "outside frame", buffer[..]) || ui.end(context) {
    #panic("invalid UI state accepted")
  }
  frame: usize = 0
  for frame < 3 {
    if !ui.begin(context) || ui.begin(context) {
      #panic("UI frame")
    }
    if !ui.window(context, "Debug", buffer[..], ui.Rectangle{ x: 10, y: 10, width: 300, height: 200 }) {
      #panic("UI window")
    }
    if !ui.label(context, "arena backed", buffer[..]) || ui.button(context, "Button", buffer[..]) < 0 {
      #panic("UI widgets")
    }
    if ui.end(context) || !ui.window_end(context) || !ui.end(context) {
      #panic("UI balance")
    }
    texts: usize = 0
    rectangles: usize = 0
    for {
      command := ui.next(context)
      if command == nil {
        break
      }
      if ui.kind(command) == ui.Text && strings.equal(ui.text(command), "arena backed") {
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
  _ = io.println(io.stdout(), "microui arena draw commands passed")
}
''',
    'enet': r'''use "vendor/enet"
use "std/time"
use "std/strings"
use "std/io"
fn main() {
  if !enet.init() {
    #panic("ENet init")
  }
  defer enet.quit()
  path: [64]u8 = []
  server := enet.listen_at_owned("0.0.0.0", 0, 2, 2, path[..])
  if server == nil {
    #panic("ENet server")
  }
  defer enet.destroy_owned(server)
  client := enet.client_channels_owned(1, 2)
  if client == nil {
    #panic("ENet client")
  }
  defer enet.destroy_owned(client)
  peer := enet.connect_channels(client, "127.0.0.1", enet.port(server), 2, path[..])
  if peer == nil {
    #panic("ENet connect")
  }
  if enet.send(nil, "bad") || enet.client_owned(0) != nil {
    #panic("invalid ENet state accepted")
  }
  deadline := time.deadline_after(5 * time.Second)
  done := false
  for !done && !time.deadline_expired(&deadline) {
    remote := enet.service(server, 0)
    if !remote.ok {
      #panic("server service")
    }
    if remote.kind == enet.Received {
      if remote.channel != 1 || !strings.equal(enet.packet_bytes(remote.packet), "ping") {
        #panic("server payload")
      }
      if !enet.send_channel(remote.peer, 1, "pong") {
        #panic("server echo")
      }
      enet.packet_destroy(remote.packet)
    }
    local := enet.service(client, 0)
    if !local.ok {
      #panic("client service")
    }
    if local.kind == enet.Connected {
      if !enet.send_channel(peer, 1, "ping") {
        #panic("client send")
      }
    }
    if local.kind == enet.Received {
      if local.channel != 1 || !strings.equal(enet.packet_bytes(local.packet), "pong") {
        #panic("client payload")
      }
      enet.packet_destroy(local.packet)
      done = true
    }
    _ = time.sleep(time.Millisecond)
  }
  if !done {
    #panic("ENet loopback timed out")
  }
  if enet.send_channel(peer, 2, "invalid") || enet.client_channels_owned(1, 256) != nil || enet.listen_at_owned("bad address", 0, 1, 1, path[..]) != nil {
    #panic("invalid ENet configuration")
  }
  enet.disconnect_with_reason(peer, 42)
  server_closed := false
  client_closed := false
  deadline = time.deadline_after(5 * time.Second)
  for (!server_closed || !client_closed) && !time.deadline_expired(&deadline) {
    server_event := enet.service(server, 0)
    client_event := enet.service(client, 0)
    if !server_event.ok || !client_event.ok {
      #panic("disconnect service")
    }
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
    _ = time.sleep(time.Millisecond)
  }
  if !server_closed || !client_closed {
    #panic("disconnect deadline")
  }
  _ = io.println(io.stdout(), "ENet reliable loopback passed")
}
''',
    'miniaudio': r'''use "vendor/miniaudio" audio
use "std/mem"
use "std/os/linux"
use "std/fs"
use "std/io"
use "std/time"
fn main() {
  storage := mem.arena_create(4 * 1024 * 1024)
  if !storage.ok {
    #panic("audio arena")
  }
  defer {
    _ = mem.arena_release(&storage.arena)
  }
  args := linux.process_arguments(&storage.arena)
  if #len(args) != 2 {
    #panic("WAV path required")
  }
  bytes := fs.read_all(&storage.arena, args[1], 1024 * 1024)
  if !bytes.ok {
    #panic("WAV read")
  }
  mark := mem.arena_mark(&storage.arena)
  if audio.decoder_create(&storage.arena, "invalid").ok || mem.arena_mark(&storage.arena) != mark {
    #panic("invalid decoder rollback")
  }
  decoder := audio.decoder_create(&storage.arena, bytes.data)
  if !decoder.ok {
    #panic("decoder")
  }
  defer audio.decoder_close(decoder.value)
  samples: [2048]f32 = []
  heard := false
  ended := false
  iterations: usize = 0
  for iterations < 200 {
    result := audio.decoder_read(decoder.value, samples[..])
    if !result.ok {
      #panic("decode read")
    }
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
  if !heard || !ended || audio.decoder_read(decoder.value, samples[..1]).ok {
    #panic("decode frames")
  }
  audio.decoder_close(decoder.value)
  if audio.decoder_read(decoder.value, samples[..]).ok {
    #panic("closed decoder accepted")
  }
  engine := audio.engine_create(&storage.arena, false)
  if !engine.ok {
    #panic("audio engine")
  }
  defer audio.engine_close(engine.value)
  path: [4096]u8 = []
  if !audio.play_file(engine.value, args[1], path[..]) {
    #panic("engine play")
  }
  heard = false
  iterations = 0
  for !heard && iterations < 200 {
    mixed := audio.mix(engine.value, samples[..])
    if !mixed.ok {
      #panic("engine mix")
    }
    for mixed_sample in samples[..mixed.samples] {
      if mixed_sample != 0.0 {
        heard = true
      }
    }
    if !heard {
      _ = time.sleep(time.Millisecond)
    }
    iterations += 1
  }
  if !heard {
    #panic("engine produced no audio")
  }
  _ = io.println(io.stdout(), "miniaudio decode and offline mixing passed")
}
''',
    'sdl3-mixer': r'''use "vendor/sdl3/mixer"
use "std/mem"
use "std/os/linux"
use "std/fs"
use "std/io"
fn main() {
  storage := mem.arena_create(4 * 1024 * 1024)
  if !storage.ok {
    #panic("audio arena")
  }
  defer {
    _ = mem.arena_release(&storage.arena)
  }
  args := linux.process_arguments(&storage.arena)
  if #len(args) != 2 {
    #panic("WAV path required")
  }
  bytes := fs.read_all(&storage.arena, args[1], 1024 * 1024)
  if !bytes.ok {
    #panic("WAV read")
  }
  if !mixer.init() {
    #panic("mixer init")
  }
  defer mixer.quit()
  engine := mixer.create_owned()
  if engine == nil {
    #panic("mixer create")
  }
  defer mixer.destroy_owned(engine)
  audio := mixer.decode_owned(engine, bytes.data)
  if audio == nil {
    #panic("mixer decode")
  }
  defer mixer.audio_destroy_owned(audio)
  if mixer.decode_owned(engine, "invalid") != nil {
    #panic("invalid audio accepted")
  }
  track := mixer.track_create(engine)
  if track == nil {
    #panic("mixer track")
  }
  defer mixer.track_destroy(track)
  if !mixer.play(track, audio) {
    #panic("mixer play")
  }
  samples: [2048]f32 = []
  heard := false
  iterations: usize = 0
  for iterations < 200 && mixer.playing(track) {
    result := mixer.generate(engine, samples[..])
    if !result.ok {
      #panic("mixer generate")
    }
    for sample in samples[..result.written] {
      if sample != 0.0 {
        heard = true
      }
    }
    iterations += 1
  }
  if !heard || mixer.playing(track) {
    #panic("mixer did not finish audio")
  }
  if !mixer.play(track, audio) || !mixer.stop(track) || mixer.playing(track) {
    #panic("mixer stop")
  }
  silent := mixer.generate(engine, samples[..])
  if !silent.ok || silent.written != 0 {
    #panic("mixer silence status")
  }
  for silent_sample in samples {
    if silent_sample != 0.0 {
      #panic("mixer silence output")
    }
  }
  if mixer.generate(engine, samples[..1]).ok {
    #panic("odd sample count accepted")
  }
  device := mixer.create_device_owned()
  if device == nil {
    #panic("mixer playback device")
  }
  defer mixer.destroy_owned(device)
  _ = io.println(io.stdout(), "SDL_mixer offline playback passed")
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
