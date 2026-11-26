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
use "std/fail"
use "std/io"
fn resize_fails(scratch: *mem.Arena, source: []const u8, width: usize, destination: []u8, out_width: usize) bool {
  status: fail.Status
  image.resize(scratch, &status, source, width, 2, destination, out_width, out_width, 4, false)
  return status.failed
}
fn packing_fails(scratch: *mem.Arena, width: usize, height: usize, rectangles: []atlas.Rectangle) bool {
  status: fail.Status
  _ = atlas.pack(scratch, &status, width, height, rectangles)
  return status.failed
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
  status := fail.Status{ on_failure: fail.panic_on_failure }
  if atlas.pack(backing, &status, 16, 16, rectangles[..]) != 3 || mem.arena_mark(backing) != mark {
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
  if atlas.pack(backing, &status, 4, 4, rectangles[..]) != 1 {
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
  image.resize(backing, &status, source[..], 2, 2, destination[..], 4, 4, 4, false)
  for value in destination[..] {
    if value != 128 {
      #panic("resize constant color")
    }
  }
  image.resize(backing, &status, source[..], 2, 2, destination[..], 4, 4, 4, true)
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
use "std/fail"
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
  status := fail.Status{ on_failure: fail.panic_on_failure }
  sdl.init_video(&status)
  defer sdl.quit()
  text: [256]u8
  window := sdl.window_create(&status, "Dyn interactive UI", text[..], 640, 360, sdl.WindowResizable)
  defer sdl.window_destroy_owned(window)
  renderer := sdl.renderer_create_default_owned(&status, window)
  defer sdl.renderer_destroy_owned(renderer)
  context := ui.create(arena, &status)
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
    ui.begin(&status, context)
    if ui.window(&status, context, "Debug panel", text[..], ui.Rectangle{ x: 20, y: 20, width: 300, height: 220 }) {
      if clicked {
        ui.label(&status, context, "Button clicked!", text[..])
      }
      else {
        ui.label(&status, context, "Click the button below", text[..])
      }
      if ui.button(&status, context, "Click me", text[..]) {
        clicked = true
      }
      ui.window_end(&status, context)
    }
    ui.end(&status, context)
    sdl.clear(&status, renderer, 20, 28, 48, 255)
    backend.render(&status, context, renderer)
    sdl.present(&status, renderer)
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
use "std/fail"
use "std/mem"
use "std/os/linux"
use io "std/io"
use "std/strings"
use "std/bytes"
use "std/time"
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
  status := fail.Status{ on_failure: fail.panic_on_failure }
  engine := audio.engine_create(arena, &status, !offline)
  defer audio.engine_close(engine)
  path: [4096]u8
  mark := mem.arena_mark(arena)
  missing: fail.Status
  _ = audio.sound_create(arena, &missing, engine, "/nonexistent/dyn-audio-fixture", path[..])
  if !missing.failed || mem.arena_mark(arena) != mark {
    #panic("sound failure rollback")
  }
  sound := audio.sound_create(arena, &status, engine, args[1], path[..])
  defer audio.sound_close(sound)
  audio.sound_volume(&status, sound, 0.5)
  negative: fail.Status
  audio.sound_volume(&negative, sound, -1.0)
  audio.sound_start(&status, sound)
  audio.sound_stop(&status, sound)
  if !negative.failed || audio.sound_playing(sound) {
    #panic("sound controls")
  }
  audio.sound_rewind(&status, sound)
  audio.sound_start(&status, sound)
  deadline := time.deadline_after(60 * time.Second)
  samples: [2048]f32
  heard := false
  for !audio.sound_ended(sound) {
    if time.deadline_expired(&deadline) { break }
    if offline {
      count := audio.mix(&status, engine, samples[..])
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
  closed: fail.Status
  audio.sound_start(&closed, sound)
  if !closed.failed {
    #panic("closed sound accepted")
  }
  io.println("audio playback completion passed")
}
''',
    'lz4': r'''use "vendor/lz4"
use "std/fail"
use io "std/io"
use "std/bytes"
fn rejected(compress: bool, destination: []u8, source: []const u8) bool {
  status: fail.Status
  if compress {
    _ = lz4.compress(&status, destination, source)
  } else {
    _ = lz4.decompress(&status, destination, source)
  }
  return status.failed
}
fn main() {
  compressed: [128]u8
  output: [128]u8
  source := "caller buffers caller buffers caller buffers"
  status := fail.Status{ on_failure: fail.panic_on_failure }
  written := lz4.compress(&status, compressed[..], source)
  decoded := lz4.decompress(&status, output[..], compressed[..written])
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
  empty := lz4.compress(&status, compressed[..], "")
  if lz4.decompress(&status, output[..0], compressed[..empty]) != 0 {
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
use "std/fail"
use "std/fs"
use "std/os/linux"
fn main() {
  document := "{\"asset\":{\"version\":\"2.0\"},\"nodes\":[{}],\"buffers\":[{\"byteLength\":12,\"uri\":\"data:application/octet-stream;base64,AAAAAAAAgD8AAABA\"}],\"bufferViews\":[{\"buffer\":0,\"byteLength\":12}],\"accessors\":[{\"bufferView\":0,\"componentType\":5126,\"count\":1,\"type\":\"VEC3\"}]}"
  status := fail.Status{ on_failure: fail.panic_on_failure }
  model := cgltf.parse_owned(&status, document)
  defer cgltf.destroy_owned(model)
  cgltf.validate(&status, model)
  cgltf.load_embedded(&status, model)
  if cgltf.node_count(model) != 1 {
    #panic("glTF validate/load")
  }
  values: [3]f32
  cgltf.read_float(&status, model, 0, 0, values[..])
  if values[0] != 0.0 || values[1] != 1.0 || values[2] != 2.0 {
    #panic("glTF accessor")
  }
  missing_accessor: fail.Status
  cgltf.read_float(&missing_accessor, model, 1, 0, values[..])
  short_output: fail.Status
  cgltf.read_float(&short_output, model, 0, 0, values[..1])
  if !missing_accessor.failed || !short_output.failed {
    #panic("glTF invalid accessor accepted")
  }
  broken: fail.Status
  _ = cgltf.parse_owned(&broken, "broken")
  if !broken.failed {
    #panic("invalid glTF accepted")
  }
  external := cgltf.parse_owned(&status, "{\"asset\":{\"version\":\"2.0\"},\"buffers\":[{\"byteLength\":12,\"uri\":\"external.bin\"}]}")
  defer cgltf.destroy_owned(external)
  unattached: fail.Status
  cgltf.load_embedded(&unattached, external)
  if unattached.failure.kind != fail.Kind.InvalidState {
    #panic("external resource not rejected")
  }
  // Application chooses how external URIs are resolved. This example supplies
  // caller-owned arrays; real tools can read files into a retained model arena.
  mesh := cgltf.parse_owned(&status, "{\"asset\":{\"version\":\"2.0\"},\"buffers\":[{\"byteLength\":36,\"uri\":\"vertices.bin\"},{\"byteLength\":6,\"uri\":\"indices.bin\"}],\"bufferViews\":[{\"buffer\":0,\"byteLength\":36},{\"buffer\":1,\"byteLength\":6}],\"accessors\":[{\"bufferView\":0,\"componentType\":5126,\"count\":3,\"type\":\"VEC3\"},{\"bufferView\":1,\"componentType\":5123,\"count\":3,\"type\":\"SCALAR\"}],\"materials\":[{\"pbrMetallicRoughness\":{\"baseColorFactor\":[1,0.5,0.25,1]}}],\"meshes\":[{\"primitives\":[{\"attributes\":{\"POSITION\":0},\"indices\":1,\"material\":0}]}],\"nodes\":[{\"mesh\":0,\"translation\":[1,2,3]}]}")
  defer cgltf.destroy_owned(mesh)
  vertices: [9]f32
  triangles: [3]u16
  triangles[1] = 1
  triangles[2] = 2
  vertex_bytes := #slice(#cast(*const u8, &vertices[0]), 36)
  index_bytes := #slice(#cast(*const u8, &triangles[0]), 6)
  short_buffer: fail.Status
  cgltf.attach_buffer(&short_buffer, mesh, 0, vertex_bytes[..1])
  if cgltf.buffer_count(mesh) != 2 || !bytes.equal(cgltf.buffer_uri(mesh, 0, 256), "vertices.bin") || cgltf.buffer_size(mesh, 0) != 36 || !short_buffer.failed {
    #panic("mesh resource metadata")
  }
  cgltf.attach_buffer(&status, mesh, 0, vertex_bytes)
  cgltf.attach_buffer(&status, mesh, 1, index_bytes)
  twice: fail.Status
  cgltf.attach_buffer(&twice, mesh, 0, vertex_bytes)
  if !twice.failed {
    #panic("mesh buffer attachment")
  }
  cgltf.load_embedded(&status, mesh)
  cgltf.validate(&status, mesh)
  position := cgltf.attribute(&status, mesh, 0, 0, cgltf.Position, 0)
  indices := cgltf.indices(&status, mesh, 0, 0)
  material := cgltf.material(&status, mesh, 0, 0)
  node_mesh := cgltf.node_mesh(&status, mesh, 0)
  if cgltf.mesh_count(mesh) != 1 || cgltf.primitive_count(mesh, 0) != 1 || cgltf.material_count(mesh) != 1 || position != 0 || indices != 1 || material != 0 || cgltf.topology(mesh, 0, 0) != cgltf.Triangles || node_mesh != 0 || cgltf.element_count(mesh, 0) != 3 {
    #panic("mesh traversal")
  }
  past: fail.Status
  _ = cgltf.read_index(&past, mesh, 1, 3)
  normal: fail.Status
  _ = cgltf.attribute(&normal, mesh, 0, 0, cgltf.Normal, 0)
  if cgltf.read_index(&status, mesh, 1, 2) != 2 || !past.failed || normal.failure.kind != fail.Kind.NotFound {
    #panic("mesh indices")
  }
  transform := cgltf.world_transform(&status, mesh, 0)
  color := cgltf.base_color(&status, mesh, 0)
  no_material: fail.Status
  _ = cgltf.base_color(&no_material, mesh, 1)
  if transform[12] != 1.0 || transform[13] != 2.0 || transform[14] != 3.0 || color[1] != 0.5 || !no_material.failed {
    #panic("mesh transform/material")
  }
  backing := mem.arena_alloc(2 * 1024 * 1024)
  defer {
    mem.arena_release(backing)
  }
  args := linux.process_arguments(backing)
  if args.len == 2 {
    file := fs.read_all(backing, args[1], 1024 * 1024) catch { #panic("cannot read a fixture") }
    binary := cgltf.parse_owned(&status, file)
    defer cgltf.destroy_owned(binary)
    cgltf.load_embedded(&status, binary)
    cgltf.read_float(&status, binary, 0, 0, values[..])
    if values[2] != 2.0 {
      #panic("GLB accessor")
    }
  }
  io.println("cgltf embedded accessor passed")
}
''',
    'box2d': r'''use physics "vendor/box2d"
use "std/fail"
use "std/io"
fn stale(body: physics.Body) bool {
  status: fail.Status
  _ = physics.position(&status, body)
  return status.failed
}
fn main() {
  status := fail.Status{ on_failure: fail.panic_on_failure }
  world := physics.create_owned(&status, 0.0, -10.0)
  defer physics.destroy_owned(world)
  ground := physics.body_create(&status, world, 0.0, -1.0, false)
  falling := physics.body_create(&status, world, 0.0, 4.0, true)
  _ = physics.box_create(&status, ground, 10.0, 1.0, 0.0)
  _ = physics.box_create(&status, falling, 0.5, 0.5, 1.0)
  bad_step: fail.Status
  physics.step(&bad_step, world, -1.0, 4)
  bad_box: fail.Status
  _ = physics.box_create(&bad_box, falling, -1.0, 1.0, 1.0)
  if !bad_step.failed || !bad_box.failed {
    #panic("invalid physics input")
  }
  circle_body := physics.body_create(&status, world, 3.0, 4.0, true)
  circle := physics.circle_create(&status, circle_body, 0.5, 1.0)
  physics.contact_events(&status, circle, true)
  bad_circle: fail.Status
  _ = physics.circle_create(&bad_circle, circle_body, -1.0, 1.0)
  if !bad_circle.failed {
    #panic("circle shape")
  }
  anchor := physics.body_create(&status, world, 20.0, 4.0, false)
  pendulum := physics.body_create(&status, world, 20.0, 2.0, true)
  _ = physics.circle_create(&status, pendulum, 0.5, 1.0)
  joint := physics.distance_joint(&status, anchor, pendulum, 2.0)
  self_joint: fail.Status
  _ = physics.distance_joint(&self_joint, anchor, anchor, 2.0)
  if !self_joint.failed {
    #panic("distance joint")
  }
  contacts := false
  for i in 0..240 {
    physics.step(&status, world, 1.0 / 60.0, 4)
    count := physics.contact_count(&status, world, true)
    for event_index in 0..count {
      event := physics.contact(&status, world, true, event_index)
      if event.first == circle || event.second == circle {
        contacts = true
      }
    }
  }
  circle_position := physics.position(&status, circle_body)
  joint_position := physics.position(&status, pendulum)
  if !contacts || circle_position.y < 0.4 || circle_position.y > 0.7 || joint_position.y < 1.9 || joint_position.y > 2.1 {
    #panic("circle contact/joint motion")
  }
  hits: [1]physics.Shape
  candidates := physics.query(&status, world, -2.0, -2.0, 5.0, 5.0, hits[..])
  inverted: fail.Status
  _ = physics.query(&inverted, world, 2.0, 2.0, -2.0, -2.0, hits[..])
  past: fail.Status
  _ = physics.contact(&past, world, true, 999)
  if candidates.total < 3 || candidates.written != 1 || !inverted.failed || past.failure.kind != fail.Kind.NotFound {
    #panic("physics query")
  }
  physics.joint_destroy(joint)
  physics.joint_destroy(joint)
  final := physics.position(&status, falling)
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
use "std/fail"
use "std/mem"
use io "std/io"
use "std/bytes"
fn rejected(step: fn(*fail.Status, ui.Context), context: ui.Context) bool {
  status: fail.Status
  step(&status, context)
  return status.failed
}
fn outside_label(status: *fail.Status, context: ui.Context) {
  buffer: [64]u8
  ui.label(status, context, "outside frame", buffer[..])
}
fn main() {
  storage := mem.arena_alloc(1024 * 1024)
  defer {
    mem.arena_release(storage)
  }
  status := fail.Status{ on_failure: fail.panic_on_failure }
  context := ui.create(storage, &status)
  buffer: [256]u8
  if !rejected(outside_label, context) || !rejected(ui.end, context) {
    #panic("invalid UI state accepted")
  }
  frame: usize = 0
  for frame < 3 {
    ui.begin(&status, context)
    if !rejected(ui.begin, context) {
      #panic("UI frame")
    }
    if !ui.window(&status, context, "Debug", buffer[..], ui.Rectangle{ x: 10, y: 10, width: 300, height: 200 }) {
      #panic("UI window")
    }
    ui.label(&status, context, "arena backed", buffer[..])
    _ = ui.button(&status, context, "Button", buffer[..])
    if !rejected(ui.end, context) {
      #panic("UI balance")
    }
    ui.window_end(&status, context)
    ui.end(&status, context)
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
use "std/fail"
use "std/time"
use io "std/io"
use "std/bytes"
fn main() {
  status := fail.Status{ on_failure: fail.panic_on_failure }
  enet.init(&status)
  defer enet.quit()
  path: [64]u8
  server := enet.listen_at_owned(&status, "0.0.0.0", 0, 2, 2, path[..])
  defer enet.destroy_owned(server)
  client := enet.client_channels_owned(&status, 1, 2)
  defer enet.destroy_owned(client)
  peer := enet.connect_channels(&status, client, "127.0.0.1", enet.port(server), 2, path[..])
  no_peer: fail.Status
  enet.send(&no_peer, nil, "bad")
  no_peers: fail.Status
  _ = enet.client_owned(&no_peers, 0)
  if !no_peer.failed || !no_peers.failed {
    #panic("invalid ENet state accepted")
  }
  deadline := time.deadline_after(5 * time.Second)
  done := false
  for !done {
    if time.deadline_expired(&deadline) { break }
    remote := enet.service(&status, server, 0)
    if remote.kind == enet.Received {
      if remote.channel != 1 || !bytes.equal(enet.packet_bytes(remote.packet), "ping") {
        #panic("server payload")
      }
      enet.send_channel(&status, remote.peer, 1, "pong")
      enet.packet_destroy(remote.packet)
    }
    local := enet.service(&status, client, 0)
    if local.kind == enet.Connected {
      enet.send_channel(&status, peer, 1, "ping")
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
  bad_channel: fail.Status
  enet.send_channel(&bad_channel, peer, 2, "invalid")
  many_channels: fail.Status
  _ = enet.client_channels_owned(&many_channels, 1, 256)
  bad_address: fail.Status
  _ = enet.listen_at_owned(&bad_address, "bad address", 0, 1, 1, path[..])
  if !bad_channel.failed || !many_channels.failed || !bad_address.failed {
    #panic("invalid ENet configuration")
  }
  enet.disconnect_with_reason(peer, 42)
  server_closed := false
  client_closed := false
  deadline = time.deadline_after(5 * time.Second)
  for (!server_closed || !client_closed) {
    if time.deadline_expired(&deadline) { break }
    server_event := enet.service(&status, server, 0)
    client_event := enet.service(&status, client, 0)
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
use "std/fail"
use "std/io"
use "std/time"
fn read_fails(decoder: rawptr, output: []f32) bool {
  status: fail.Status
  _ = audio.decoder_read(&status, decoder, output)
  return status.failed
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
  status := fail.Status{ on_failure: fail.panic_on_failure }
  bytes := fs.read_all(storage, args[1], 1024 * 1024) catch { #panic("cannot read a fixture") }
  mark := mem.arena_mark(storage)
  invalid: fail.Status
  _ = audio.decoder_create(storage, &invalid, "invalid")
  if !invalid.failed || mem.arena_mark(storage) != mark {
    #panic("invalid decoder rollback")
  }
  decoder := audio.decoder_create(storage, &status, bytes)
  defer audio.decoder_close(decoder)
  samples: [2048]f32
  heard := false
  ended := false
  iterations: usize = 0
  for iterations < 200 {
    result := audio.decoder_read(&status, decoder, samples[..])
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
  engine := audio.engine_create(storage, &status, false)
  defer audio.engine_close(engine)
  path: [4096]u8
  audio.play_file(&status, engine, args[1], path[..])
  heard = false
  iterations = 0
  for !heard && iterations < 200 {
    count := audio.mix(&status, engine, samples[..])
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
use "std/fail"
use "std/fs"
use "std/io"
fn main() {
  storage := mem.arena_alloc(4 * 1024 * 1024)
  defer {
    mem.arena_release(storage)
  }
  args := linux.process_arguments(storage)
  if args.len != 2 {
    #panic("WAV path required")
  }
  status := fail.Status{ on_failure: fail.panic_on_failure }
  bytes := fs.read_all(storage, args[1], 1024 * 1024) catch { #panic("cannot read a fixture") }
  mixer.init(&status)
  defer mixer.quit()
  engine := mixer.create_owned(&status)
  defer mixer.destroy_owned(engine)
  audio := mixer.decode_owned(&status, engine, bytes)
  defer mixer.audio_destroy_owned(audio)
  invalid: fail.Status
  if mixer.decode_owned(&invalid, engine, "invalid") != nil || !invalid.failed {
    #panic("invalid audio accepted")
  }
  track := mixer.track_create(&status, engine)
  defer mixer.track_destroy(track)
  mixer.play(&status, track, audio)
  samples: [2048]f32
  heard := false
  iterations: usize = 0
  for iterations < 200 && mixer.playing(track) {
    written := mixer.generate(&status, engine, samples[..])
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
  mixer.play(&status, track, audio)
  mixer.stop(&status, track)
  if mixer.playing(track) {
    #panic("mixer stop")
  }
  if mixer.generate(&status, engine, samples[..]) != 0 {
    #panic("mixer silence status")
  }
  for silent_sample in samples {
    if silent_sample != 0.0 {
      #panic("mixer silence output")
    }
  }
  odd: fail.Status
  _ = mixer.generate(&odd, engine, samples[..1])
  if !odd.failed {
    #panic("odd sample count accepted")
  }
  device := mixer.create_device_owned(&status)
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
