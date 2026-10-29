#!/usr/bin/env python3
"""Batched OpenGL UI renderer against the software oracle: rounded SDF rectangles, glyph atlas, few draw calls. Requires DISPLAY and GL 3.3."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "vendor/window" window
use "vendor/opengl" gl
use "vendor/ui/opengl" gpu
use "std/ui" ui
use "std/ui/box" box
use "std/ui/software" software
use "std/mem" mem
use "std/errors" errors

fn check(ok: bool, message: []const u8) {
  if !ok {
    #panic(message)
  }
}

coverage: [48]u8

// A 6x8 block glyph for every code point, with a soft right column.
fn bitmap(data: rawptr, codepoint: u32) software.Glyph {
  _ = data
  _ = codepoint
  return software.Glyph{ pixels: coverage[..], width: 6, height: 8, stride: 6, advance: 7, y_offset: 2 }
}

fn measure(data: rawptr, text: []const u8) f32 {
  _ = data
  return 7.0 * #cast(f32, #len(text))
}

fn build(state: *box.State, context: *ui.Context, arena: *mem.Arena) {
  mem.arena_reset(arena)
  ui.begin(context, arena, ui.Input{}, ui.Rect{ width: 160, height: 96 })
  box.begin(state, arena, box.Input{}, 160.0, 96.0, 1.0 / 60.0)
  panel := box.build(state, box.DrawBackground, "panel")
  panel.width = box.percent(1.0, 1.0)
  panel.height = box.percent(1.0, 1.0)
  panel.background = ui.Color{ r: 20, g: 22, b: 28, a: 255 }
  box.push_parent(state, panel)
  _ = box.button(state, "Open")
  _ = box.button(state, "Save as")
  _ = box.label(state, "Hello")
  card := box.build(state, box.DrawBackground, "card")
  card.width = box.pixels(60.0, 1.0)
  card.height = box.pixels(20.0, 1.0)
  card.radius = 9
  card.background = ui.Color{ r: 200, g: 90, b: 40, a: 160 }
  box.pop_parent(state)
  box.end(state, context)
  ui.end(context)
}

fn main() {
  persistent_arena = mem.arena_create(0)
  defer mem.arena_release(persistent_arena)
  for i in 0..48 {
    coverage[i] = 255
    if i % 6 == 5 {
      coverage[i] = 96
    }
  }
  host := window.Window{}
  check(window.open(&host, "Dyn batched UI test", 160, 96).ok, "window")
  defer {
    window.close(&host)
  }
  loaded := gl.load(window.gl_proc)
  check(loaded.ok, "gl")
  batch := mem.push(gpu.Batch, persistent_arena)
  check(gpu.open_batch(batch, loaded.api).ok, "open batch")
  defer {
    gpu.close_batch(batch)
  }
  arena := mem.arena_create(16777216)
  defer {
    mem.arena_release(arena)
  }
  state := box.create(persistent_arena, measure, nil, 12.0)
  context: ui.Context
  build(state, &context, arena)
  build(state, &context, arena)
  font := software.Font{ glyph: bitmap, line_height: 12 }
  pixels := mem.push_array(u8, persistent_arena, #cast(usize, 61440))
  surface := software.Surface{ pixels: pixels, width: 160, height: 96, stride: 640 }
  check(software.render(&surface, ui.first(&context), font).ok, "software")
  vertices := mem.push_array(f32, persistent_arena, #cast(usize, 86016))
  loaded.api.clear_color(0.0, 0.0, 0.0, 0.0)
  loaded.api.clear(gl.ColorBufferBit)
  check(gpu.render_batch(batch, ui.first(&context), 160, 96, font, vertices).ok, "batch render")
  actual := mem.push_array(u8, persistent_arena, #cast(usize, 61440))
  loaded.api.read_pixels(0, 0, 160, 96, gl.Rgba, gl.UnsignedByte, &actual[0])
  worst: i32 = 0
  for y in 0..96 {
    for x in 0..160 {
      for channel in 0..4 {
        difference := #cast(i32, pixels[(y * 160 + x) * 4 + channel]) - #cast(i32, actual[((95 - y) * 160 + x) * 4 + channel])
        if difference < 0 {
          difference = -difference
        }
        if difference > worst {
          worst = difference
        }
      }
    }
  }
  check(worst <= 2, "GPU matches the software oracle within 2/255")
  // One clip for the whole frame: one draw call, glyphs uploaded once each.
  check(batch.draw_calls == 1, "single draw call")
  uploads := batch.uploads
  check(uploads >= 1 && uploads <= 12, "atlas uploads distinct glyphs")
  check(gpu.render_batch(batch, ui.first(&context), 160, 96, font, vertices).ok, "second render")
  check(batch.uploads == uploads, "cached glyphs are not uploaded again")
  // Tiny vertex storage still renders, with more draw calls.
  tiny: [84]f32 = []
  calls := batch.draw_calls
  check(gpu.render_batch(batch, ui.first(&context), 160, 96, font, tiny[..]).ok, "tiny stream")
  check(batch.draw_calls - calls > 5, "tiny stream flushes often")
  check(gpu.render_batch(batch, ui.first(&context), 160, 96, font, tiny[..10]).kind == errors.Kind.InvalidInput, "stream too small")
  check(window.poll(&host).ok && window.swap(&host).ok, "present")
}

persistent_arena: *mem.Arena
'''
CLIPBOARD = r'''use "vendor/window" window
use "std/bytes" bytes
use "std/time" time

fn check(ok: bool, message: []const u8) {
  if !ok {
    #panic(message)
  }
}

fn main() {
  source := window.Window{}
  target := window.Window{}
  check(window.open(&source, "source", 64, 64).ok, "source")
  defer {
    window.close(&source)
  }
  check(window.open(&target, "target", 64, 64).ok, "target")
  defer {
    window.close(&target)
  }
  check(window.scale(&source) > 0.0, "scale")
  window.set_cursor(&source, window.Cursor.Text)
  window.set_cursor(&source, window.Cursor.Hand)
  window.set_clipboard(&source, "héllo clipboard")
  window.request_paste(&target)
  got := false
  for i in 0..200 {
    _ = window.poll(&source)
    _ = window.poll(&target)
    input := window.box_input(&target)
    if input.paste {
      check(bytes.equal(input.clipboard, "héllo clipboard"), "pasted text")
      got = true
      break
    }
    window.wait(&target, 10)
  }
  check(got, "paste arrived")
  // Pasting into the owner needs no round trip.
  window.request_paste(&source)
  _ = window.poll(&source)
  check(window.box_input(&source).paste && bytes.equal(window.box_input(&source).clipboard, "héllo clipboard"), "owner paste on the next poll")
  _ = window.poll(&source)
  check(!window.box_input(&source).paste, "paste lasts one frame")
  start := time.monotonic_now().value
  window.wait(&source, 50)
  elapsed := time.elapsed(start, time.monotonic_now().value).value
  check(elapsed < 2 * time.Second, "wait returns")
}
'''
if not sys.platform.startswith('linux') or not os.environ.get('DISPLAY'):
    print('SKIP batched UI: DISPLAY unavailable')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-ui-batch-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE)
    for flags in (['--debug'], ['--release'], ['--release', '--opt-level', '3']):
        output = work / 'program'
        subprocess.run([DYN, 'build', str(work), *flags, '--quiet', '--no-cache', '--output', str(output)], check=True, timeout=300)
        subprocess.run([str(output)], check=True, timeout=60)
    clipboard = work / 'clipboard'
    clipboard.mkdir()
    (clipboard / 'main.dyn').write_text(CLIPBOARD)
    subprocess.run([DYN, 'build', str(clipboard), '--quiet', '--no-cache', '--output', str(clipboard / 'program')], check=True, timeout=300)
    subprocess.run([str(clipboard / 'program')], check=True, timeout=60)
    viewer = work / 'box-viewer'
    subprocess.run([DYN, 'build', str(ROOT / 'examples/box-viewer'), '--release', '--quiet', '--no-cache', '--output', str(viewer)], check=True, timeout=300)
    font = Path('/usr/share/fonts/noto/NotoSans-Regular.ttf')
    if font.exists():
        shot = work / 'viewer.png'
        subprocess.run([str(viewer), str(font), '--frames', '5', '--screenshot', str(shot)], check=True, timeout=60)
        assert shot.stat().st_size > 1000
print('PASS batched UI: rounded SDF rectangles and atlas glyphs match the software oracle in one draw call; glyph cache, small streams (debug/O2/O3); X11 clipboard between windows, cursors, wait; box-viewer example runs')
