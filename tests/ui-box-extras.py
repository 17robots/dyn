#!/usr/bin/env python3
"""Composed box widgets: tab selection, popups, tooltips and splitter capture."""
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
fn check(ok: bool, message: []const u8) { if !ok { #panic(message) } }
fn measure(data: rawptr, text: []const u8) f32 { _ = data
  return #cast(f32, #len(text)) * 8.0
}
fn start(state: *box.State, frame: *mem.Arena, context: *ui.Context, input: box.Input) {
  mem.arena_reset(frame)
  ui.begin(context, frame, ui.Input{}, ui.Rect{ width: 800, height: 400 })
  box.begin(state, frame, input, 800.0, 400.0, 1.0 / 60.0)
}
fn finish(state: *box.State, context: *ui.Context) {
  box.end(state, context)
  ui.end(context)
}
fn main() {
  persistent := mem.Arena{}
  frame := mem.Arena{}
  defer { mem.arena_release(&frame)
    mem.arena_release(&persistent) }
  context: ui.Context
  state := box.create(&persistent, measure, nil, 16.0)
  state.reduced_motion = true
  selected: usize = 0
  // Hover, press and release a tab. Selection changes on activation only.
  for step in 0..4 {
    start(state, &frame, &context, box.Input{ x: 10.0, y: 5.0, down: step == 2 })
    result := box.tab(state, "Second", 1, &selected)
    if step < 3 { check(selected == 0, "tab waits for release") }
    if step == 3 {
      check(result.clicked && selected == 1, "tab activates")
      check(result.box.background.r == result.box.active_color.r, "tab selected style")
    }
    tooltip := box.tooltip(state, "tip", "Helpful text", result.box)
    if step == 0 { check(tooltip == nil, "tooltip waits for hover") }
    if step == 2 {
      check(tooltip != nil && bytes.equal(tooltip.text, "Helpful text"), "tooltip snapshots text")
      check(tooltip.parent == state.root, "tooltip is root overlay")
    }
    finish(state, &context)
  }
  start(state, &frame, &context, box.Input{ x: 700.0, y: 300.0 })
  target := box.tab(state, "Second", 1, &selected)
  check(box.tooltip(state, "tip", "Hidden", target.box) == nil, "tooltip leaves target")
  check(box.tooltip(state, "nil-tip", "Hidden", nil) == nil, "nil tooltip target")
  finish(state, &context)

  menu_state := box.create(&persistent, measure, nil, 16.0)
  menu := box.Menu{}
  // Open the popup through its trigger.
  for step in 0..4 {
    start(menu_state, &frame, &context, box.Input{ x: 10.0, y: 5.0, down: step == 2 })
    _ = box.menu_button(menu_state, "File", &menu)
    if box.menu_begin(menu_state, "file-menu", &menu) {
      _ = box.menu_item(menu_state, "Open", &menu)
      box.menu_end(menu_state)
    }
    if step < 3 { check(!menu.open, "menu waits for trigger release") }
    finish(menu_state, &context)
  }
  check(menu.open, "menu trigger opens")
  check(menu.anchor[1] == 26.0, "menu anchors under trigger")
  for step in 0..3 {
    start(menu_state, &frame, &context, box.Input{ x: 10.0, y: 35.0, down: step == 1 })
    _ = box.menu_button(menu_state, "File", &menu)
    check(box.menu_begin(menu_state, "file-menu", &menu), "menu remains open")
    item := box.menu_item(menu_state, "Open", &menu)
    if step == 2 { check(item.clicked && !menu.open, "menu item closes popup") }
    box.menu_end(menu_state)
    finish(menu_state, &context)
  }
  menu.open = true
  start(menu_state, &frame, &context, box.Input{ escape: true })
  check(!box.menu_begin(menu_state, "file-menu", &menu) && !menu.open, "escape closes menu")
  check(box.parent(menu_state) == menu_state.root, "closed menu balances stack")
  finish(menu_state, &context)

  split_state := box.create(&persistent, measure, nil, 16.0)
  split_state.scale = 2.0
  split := box.Split{ position: 100.0 }
  for step in 0..5 {
    pointer: f32 = 210.0
    if step >= 3 { pointer = 250.0 }
    if step == 4 { pointer = 270.0 }
    start(split_state, &frame, &context, box.Input{ x: pointer, y: 10.0, down: step == 2 || step == 3 })
    group := box.row(split_state, "panes")
    group.width = box.pixels(306.0, 1.0)
    group.height = box.pixels(80.0, 1.0)
    box.push_parent(split_state, group)
    _ = box.spacer(split_state, "left", box.pixels(split.position, 1.0), box.percent(1.0, 1.0))
    signal := box.splitter(split_state, "divider", 0, 300.0, 40.0, &split)
    _ = box.spacer(split_state, "right", box.pixels(300.0 - split.position, 1.0), box.percent(1.0, 1.0))
    box.pop_parent(split_state)
    if step == 2 { check(signal.pressed, "splitter captures") }
    if step == 3 { check(signal.dragging && split.position == 120.0, "splitter converts display scale") }
    if step == 4 { check(signal.released && split.position == 130.0, "splitter consumes final release movement") }
    finish(split_state, &context)
  }
  split.position = -10.0
  start(split_state, &frame, &context, box.Input{})
  _ = box.splitter(split_state, "clamped", 1, 50.0, 40.0, &split)
  check(split.position == 25.0, "splitter shares undersized extent")
  finish(split_state, &context)
  start(split_state, &frame, &context, box.Input{})
  _ = box.splitter(split_state, "empty", 1, -1.0, 0.0, &split)
  check(split.position == 0.0, "splitter handles empty extent")
  finish(split_state, &context)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-ui-box-extras-') as directory:
    project = Path(directory)
    (project / 'main.dyn').write_text(SOURCE)
    for mode in ('--debug', '--release'):
        output = project / 'test'
        subprocess.run([DYN, 'build', str(project), mode, '--quiet', '--output', str(output)], check=True, timeout=300)
        subprocess.run([str(output)], check=True, timeout=90)
    for target in ('aarch64-macos', 'x86_64-windows', 'wasm32-wasi'):
        subprocess.run([DYN, 'build', str(project), '--release', '--quiet', '--target', target,
                        '--output', str(project / target)], check=True, timeout=300)
print('PASS box extras: tabs, tooltip ownership/visibility, popup trigger/item/Escape, scaled splitter capture and bounds (debug/release, desktop/WASI cross-builds)')
