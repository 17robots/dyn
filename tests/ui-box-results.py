#!/usr/bin/env python3
"""std/ui/box: keyed boxes, semantic-size layout, previous-frame input, widgets, text editing, virtual lists and animation."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/ui" ui
use "std/ui/box" box
use "std/mem" mem
use "std/bytes" bytes

fn measure(data: rawptr, text: []const u8) f32 {
  _ = data
  return 8.0 * #cast(f32, #len(text))
}

fn check(ok: bool, message: []const u8) {
  if !ok {
    #panic(message)
  }
}

struct App {
  clicks: i32,
  enabled: bool,
  volume: f32,
  name: [32]u8,
  edit: box.Edit,
  first: usize,
  last: usize,
  button_rect: [4]f32,
  list_box: *box.Box,
}

fn frame(state: *box.State, context: *ui.Context, arena: *mem.Arena, app: *App, input: box.Input) {
  mem.arena_reset(arena)
  ui.begin(context, arena, ui.Input{}, ui.Rect{ width: 400, height: 300 })
  box.begin(state, arena, input, 400.0, 300.0, 1.0 / 60.0)
  top := box.row(state, "top")
  box.push_parent(state, top)
  pressed := box.button(state, "Press##button")
  if pressed.clicked {
    app.clicks += 1
  }
  app.button_rect = pressed.box.rect
  _ = box.checkbox(state, "Enabled", &app.enabled)
  _ = box.slider(state, "volume", &app.volume, 0.0, 10.0)
  box.pop_parent(state)
  _ = box.text_field(state, "name", app.name[..], &app.edit)
  range := box.list_begin(state, "list", box.percent(1.0, 0.0), box.pixels(100.0, 1.0), 1000, 20.0)
  app.list_box = box.parent(state)
  app.first = range.first
  app.last = range.last
  for i in range.first..range.last {
    row := box.build_key(state, box.DrawText, box.key(app.list_box.key, "row") + #cast(u64, i), "row")
    row.width = box.percent(1.0, 0.0)
    row.height = box.pixels(20.0, 1.0)
  }
  box.list_end(state)
  box.end(state, context)
  ui.end(context)
}

fn main() {
  persistent := mem.arena_create(16777216)
  arena := mem.arena_create(16777216)
  defer {
    mem.arena_release(&persistent)
    mem.arena_release(&arena)
  }
  state := box.create(&persistent, measure, nil, 16.0)
  context: ui.Context
  app := App{}
  frame(state, &context, &arena, &app, box.Input{})
  // Rectangles read while building come from the previous frame's layout.
  check(app.button_rect[2] == 0.0, "first frame has no layout yet")
  frame(state, &context, &arena, &app, box.Input{})
  // Button: "Press" is 5 * 8 + 2 * 10 wide, 16 + 2 * 5 tall, at the origin.
  check(app.button_rect[0] == 0.0 && app.button_rect[2] == 60.0 && app.button_rect[3] == 26.0, "button layout")
  // Hover, press and release over the button.
  frame(state, &context, &arena, &app, box.Input{ x: 10.0, y: 10.0 })
  frame(state, &context, &arena, &app, box.Input{ x: 10.0, y: 10.0, down: true })
  frame(state, &context, &arena, &app, box.Input{ x: 10.0, y: 10.0 })
  check(app.clicks == 1, "button click")
  // Pressing and releasing outside does not click.
  frame(state, &context, &arena, &app, box.Input{ x: 10.0, y: 10.0, down: true })
  frame(state, &context, &arena, &app, box.Input{ x: 300.0, y: 290.0 })
  check(app.clicks == 1, "release outside")
  // Checkbox sits after the button: 60 + 7 * 8 + 28 wide.
  frame(state, &context, &arena, &app, box.Input{ x: 70.0, y: 10.0 })
  frame(state, &context, &arena, &app, box.Input{ x: 70.0, y: 10.0, down: true })
  frame(state, &context, &arena, &app, box.Input{ x: 70.0, y: 10.0 })
  check(app.enabled, "checkbox toggles")
  // Slider track starts at 60 + 84 = 144 and is 160 wide.
  frame(state, &context, &arena, &app, box.Input{ x: 224.0, y: 10.0 })
  frame(state, &context, &arena, &app, box.Input{ x: 224.0, y: 10.0, down: true })
  check(app.volume > 4.9 && app.volume < 5.1, "slider press")
  frame(state, &context, &arena, &app, box.Input{ x: 900.0, y: 10.0, down: true })
  check(app.volume == 10.0, "slider drag clamps")
  frame(state, &context, &arena, &app, box.Input{ x: 900.0, y: 10.0 })
  // Text field under the row: focus, type, move and delete.
  frame(state, &context, &arena, &app, box.Input{ x: 20.0, y: 30.0 })
  frame(state, &context, &arena, &app, box.Input{ x: 20.0, y: 30.0, down: true })
  frame(state, &context, &arena, &app, box.Input{ x: 20.0, y: 30.0, text: "héllo" })
  check(bytes.equal(app.name[..app.edit.length], "héllo") && app.edit.cursor == 6, "typing")
  frame(state, &context, &arena, &app, box.Input{ left: true })
  frame(state, &context, &arena, &app, box.Input{ left: true })
  frame(state, &context, &arena, &app, box.Input{ left: true })
  frame(state, &context, &arena, &app, box.Input{ backspace: true })
  check(bytes.equal(app.name[..app.edit.length], "hllo") && app.edit.cursor == 1, "utf-8 backspace")
  frame(state, &context, &arena, &app, box.Input{ paste: true, clipboard: "XY" })
  check(bytes.equal(app.name[..app.edit.length], "hXYllo"), "paste")
  frame(state, &context, &arena, &app, box.Input{ copy: true })
  check(bytes.equal(state.copied, "hXYllo"), "copy")
  // Clicking elsewhere drops focus; typing then changes nothing.
  frame(state, &context, &arena, &app, box.Input{ x: 390.0, y: 290.0, down: true })
  frame(state, &context, &arena, &app, box.Input{ x: 390.0, y: 290.0, text: "z" })
  check(app.edit.length == 6, "focus cleared")
  // Virtual list: 1000 rows, only visible ones are built.
  check(app.first == 0 && app.last <= 7, "list visible rows")
  for i in 0..120 {
    frame(state, &context, &arena, &app, box.Input{ x: 50.0, y: 100.0, scroll_y: 2000.0 })
  }
  check(app.list_box.view[1] == 19900.0, "scroll clamps to content")
  check(app.first >= 994 && app.last == 1000, "list follows scroll")
  check(!box.animating(state), "animation settles")
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-ui-box-') as directory:
    project = Path(directory)
    (project / 'main.dyn').write_text(SOURCE)
    for mode in ('--debug', '--release'):
        output = project / 'program'
        subprocess.run([DYN, 'build', str(project), mode, '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=300)
        subprocess.run([str(output)], check=True, timeout=60)
    for target in ('aarch64-macos', 'x86_64-windows', 'wasm32-wasi'):
        subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--target', target, '--output', str(project / ('program-' + target))], check=True, timeout=300)
print('PASS ui box: layout, previous-frame input, button, checkbox, slider, text field, clipboard, focus, virtual list, scroll clamp, settled animation (debug/release)')
