#!/usr/bin/env python3
"""Self-contained portable template result contracts, debug and release."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build' / ('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve()
SOURCE = r'''use text "std/text/template"
use html "std/html/template"
use io "std/io"
use mem "std/mem"
use bytes "std/bytes"
use parse "std/parse"
fn check(ok: bool) { if !ok { #panic("template results") } }
struct Sink { calls: usize }
fn refuse(data: rawptr, source: []const u8) usize!io.IoErr {
  state := #cast(*Sink, data)
  state.calls += 1
  fail .Capacity
}
fn custom(destination: io.Writer, value: []const u8) !io.IoErr {
  fail .Unsupported
}
// A parse's template, or ok false and the failure's offset.
struct Parsed { value: text.Template, ok: bool, offset: usize }
fn parse(mode: usize, arena: *mem.Arena, source: []const u8) Parsed {
  if mode == 0 {
    value := text.parse(arena, source) catch err { return Parsed{ offset: parse.offset(err) } }
    return Parsed{ value: value, ok: true }
  }
  value := html.parse(arena, source) catch err { return Parsed{ offset: parse.offset(err) } }
  return Parsed{ value: value, ok: true }
}
fn render_with(mode: usize, writer: io.Writer, template: *const text.Template, fields: []const text.Field) !io.IoErr {
  if mode == 0 {
    try text.render(writer, template, fields)
    return
  }
  try html.render(writer, template, fields)
}
fn render_ok(mode: usize, writer: io.Writer, template: *const text.Template, fields: []const text.Field) bool {
  render_with(mode, writer, template, fields) catch { return false }
  return true
}
fn render_err(mode: usize, writer: io.Writer, template: *const text.Template, fields: []const text.Field) io.IoErr {
  render_with(mode, writer, template, fields) catch err { return err }
  #panic("render should fail")
}
fn custom_err(writer: io.Writer, template: *const text.Template, fields: []const text.Field, field: fn(io.Writer, []const u8) !io.IoErr) io.IoErr {
  text.render_with(writer, template, fields, field) catch err { return err }
  #panic("render_with should fail")
}
fn named(err: io.IoErr) []const u8 {
  case err {
    .Capacity => { return "Capacity" }
    .InvalidInput => { return "InvalidInput" }
    .Unsupported => { return "Unsupported" }
    _ => { return "other" }
  }
}
fn main() {
  storage: [4096 + mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(storage[..])
  empty: text.Template
  writer: io.Writer
  fields: [1]text.Field = [text.Field{ name: "x", value: "<&>\"'" }]
  check(render_ok(0, writer, &empty, fields[..]))
  check(render_ok(1, writer, &empty, fields[..]))
  for mode in 0..2 {
    // Validation and empty input need no storage, even in a full fixed arena.
    tiny_storage: [1 + mem.ArenaBufferOverhead]u8
    tiny := mem.arena_from_buffer(tiny_storage[..])
    tiny = mem.arena_from_buffer(tiny.data[..mem.ArenaHeader + 1])
    _ = mem.push<u8>(tiny)
    tiny_mark := mem.arena_mark(tiny)
    tiny_result := parse(mode, tiny, "")
    check(tiny_result.ok && tiny_result.value.source.len == 0 && mem.arena_mark(tiny) == tiny_mark)
    tiny_result = parse(mode, tiny, "ab{{ }}")
    check(!tiny_result.ok && tiny_result.offset == 2 && tiny_result.value.source.len == 0 && mem.arena_mark(tiny) == tiny_mark)
    mark := mem.arena_mark(arena)
    parsed := parse(mode, arena, "")
    check(parsed.ok && parsed.value.source.len == 0 && mem.arena_mark(arena) == mark)
    invalid: [3][]const u8 = ["{{", "ab{{ }}", "a{{x!}}"]
    offsets: [3]usize = [0, 2, 1]
    for i in 0..3 {
      parsed = parse(mode, arena, invalid[i])
      check(!parsed.ok && parsed.offset == offsets[i] && parsed.value.source.len == 0 && mem.arena_mark(arena) == mark)
    }
    source: [10]u8 = ['<','b','>','{','{','x','}','}','!','!']
    parsed = parse(mode, arena, source[..])
    check(parsed.ok)
    source[0] = '?'
    check(parsed.value.source[0] == '<') // parse owns an arena copy.
    output: [128]u8
    buffer := io.buffer_writer(output[..])
    check(render_ok(mode, io.buffer_writer_adapter(&buffer), &parsed.value, fields[..]))
    if mode == 0 { check(bytes.equal(io.buffer_writer_bytes(&buffer), "<b><&>\"'!!")) } else { check(bytes.equal(io.buffer_writer_bytes(&buffer), "<b>&lt;&amp;&gt;&quot;&#39;!!")) }
    sink := Sink{}
    failing := io.Writer{ data: &sink, write: refuse }
    rendered := render_err(mode, failing, &parsed.value, fields[..])
    check(bytes.equal(named(rendered), "Capacity") && sink.calls == 1)
    field_only := text.Template{ source: "{{x}}tail" }
    sink.calls = 0
    rendered = render_err(mode, failing, &field_only, fields[..])
    check(bytes.equal(named(rendered), "Capacity") && sink.calls == 1)
    mem.arena_rewind(arena, mark)
  }
  seam := text.Template{ source: "{{x}}tail" }
  check(bytes.equal(named(custom_err(writer, &seam, fields[..], custom)), "Unsupported"))
  check(bytes.equal(named(render_err(0, writer, nil, fields[..])), "InvalidInput"))
  check(bytes.equal(named(custom_err(writer, &empty, fields[..], nil)), "InvalidInput"))
}
'''

# Nonempty literals retain an arena copy; storage exhaustion must panic rather
# than return a portable parse failure. Keep each wrapper in its own process.
PANIC_SOURCE = r'''use template "std/PACKAGE/template"
use mem "std/mem"
fn main() {
  storage: [1 + mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(storage[..])
  arena = mem.arena_from_buffer(arena.data[..mem.ArenaHeader + 1])
  _ = template.parse(arena, "ab") catch { #panic("parse failed") }
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-template-results-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE, encoding='utf-8')
    for mode in ('debug', 'release'):
        output = work / ('template-' + mode + ('.exe' if os.name == 'nt' else ''))
        subprocess.run([str(DYN), 'build', str(work), '--' + mode, '--quiet', '--no-cache', '--output', str(output)], cwd=ROOT, env=dict(os.environ, DYN_SDK=str(ROOT)), check=True, timeout=120)
        subprocess.run([str(output)], check=True, timeout=15)
        print('PASS template results ' + mode, flush=True)
    for package in ('text', 'html'):
        (work / 'main.dyn').write_text(PANIC_SOURCE.replace('PACKAGE', package), encoding='utf-8')
        for mode in ('debug', 'release'):
            output = work / ('exhaust-' + package + '-' + mode + ('.exe' if os.name == 'nt' else ''))
            subprocess.run([str(DYN), 'build', str(work), '--' + mode, '--quiet', '--no-cache', '--output', str(output)], cwd=ROOT, env=dict(os.environ, DYN_SDK=str(ROOT)), check=True, timeout=120)
            result = subprocess.run([str(output)], capture_output=True, timeout=15)
            assert result.returncode != 0 and b'arena exhausted' in result.stderr, (package, mode, result)
            print('PASS template arena exhaustion ' + package + ' ' + mode, flush=True)
