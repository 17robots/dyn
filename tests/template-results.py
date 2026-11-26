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
use "std/fail"
use io "std/io"
use mem "std/mem"
use bytes "std/bytes"
fn check(ok: bool) { if !ok { #panic("template results") } }
struct Sink { calls: usize, code: isize }
fn refuse(data: rawptr, source: []const u8) usize!io.IoErr {
  status: fail.Status
  count := refuse_status(data, &status, source)
  try io.check_status(&status)
  return count
}
fn refuse_status(data: rawptr, status: *fail.Status, source: []const u8) usize {
  state := #cast(*Sink, data)
  state.calls += 1
  failure := fail.make(fail.Kind.Capacity, "write", "", "full")
  failure.native = state.code
  fail.set(status, failure)
  return 0
}
fn custom(status: *fail.Status, destination: io.Writer, value: []const u8) {
  failure := fail.make(fail.Kind.Unsupported, "render field", "", "custom")
  failure.native = -73
  fail.set(status, failure)
}
struct Parsed { value: text.Template, failure: fail.Failure }
fn parse(mode: usize, arena: *mem.Arena, source: []const u8) Parsed {
  status: fail.Status
  value := text.Template{}
  if mode == 0 { value = text.parse(arena, &status, source) } else { value = html.parse(arena, &status, source) }
  return Parsed{ value: value, failure: status.failure }
}
fn render(mode: usize, writer: io.Writer, template: *const text.Template, fields: []const text.Field) fail.Failure {
  status: fail.Status
  if mode == 0 { text.render(&status, writer, template, fields) } else { html.render(&status, writer, template, fields) }
  return status.failure
}
fn main() {
  storage: [4096 + mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(storage[..])
  empty: text.Template
  writer: io.Writer
  fields: [1]text.Field = [text.Field{ name: "x", value: "<&>\"'" }]
  check(render(0, writer, &empty, fields[..]).kind == fail.Kind.Ok)
  check(render(1, writer, &empty, fields[..]).kind == fail.Kind.Ok)
  for mode in 0..2 {
    // Validation and empty input need no storage, even in a full fixed arena.
    tiny_storage: [1 + mem.ArenaBufferOverhead]u8
    tiny := mem.arena_from_buffer(tiny_storage[..])
    tiny = mem.arena_from_buffer(tiny.data[..mem.ArenaHeader + 1])
    _ = mem.push<u8>(tiny)
    tiny_mark := mem.arena_mark(tiny)
    tiny_result := parse(mode, tiny, "")
    check(tiny_result.failure.kind == fail.Kind.Ok && tiny_result.value.source.len == 0 && mem.arena_mark(tiny) == tiny_mark)
    tiny_result = parse(mode, tiny, "ab{{ }}")
    check(tiny_result.failure.kind == fail.Kind.InvalidInput && tiny_result.failure.offset == 2 && tiny_result.value.source.len == 0 && mem.arena_mark(tiny) == tiny_mark)
    mark := mem.arena_mark(arena)
    parsed := parse(mode, arena, "")
    check(parsed.failure.kind == fail.Kind.Ok && parsed.value.source.len == 0 && mem.arena_mark(arena) == mark)
    invalid: [3][]const u8 = ["{{", "ab{{ }}", "a{{x!}}"]
    offsets: [3]usize = [0, 2, 1]
    for i in 0..3 {
      parsed = parse(mode, arena, invalid[i])
      check(parsed.failure.kind == fail.Kind.InvalidInput && parsed.failure.offset == offsets[i] && parsed.value.source.len == 0 && mem.arena_mark(arena) == mark)
    }
    source: [10]u8 = ['<','b','>','{','{','x','}','}','!','!']
    parsed = parse(mode, arena, source[..])
    check(parsed.failure.kind == fail.Kind.Ok)
    source[0] = '?'
    check(parsed.value.source[0] == '<') // parse owns an arena copy.
    output: [128]u8
    buffer := io.buffer_writer(output[..])
    check(render(mode, io.buffer_writer_adapter(&buffer), &parsed.value, fields[..]).kind == fail.Kind.Ok)
    if mode == 0 { check(bytes.equal(io.buffer_writer_bytes(&buffer), "<b><&>\"'!!")) } else { check(bytes.equal(io.buffer_writer_bytes(&buffer), "<b>&lt;&amp;&gt;&quot;&#39;!!")) }
    for code in [0, -91] {
      sink := Sink{ code: code }
      failing := io.Writer{ data: &sink, write: refuse }
      rendered := render(mode, failing, &parsed.value, fields[..])
      check(rendered.kind == fail.Kind.Capacity && sink.calls == 1)
      field_only := text.Template{ source: "{{x}}tail" }
      sink.calls = 0
      rendered = render(mode, failing, &field_only, fields[..])
      check(rendered.kind == fail.Kind.Capacity && sink.calls == 1)
    }
    mem.arena_rewind(arena, mark)
  }
  seam := text.Template{ source: "{{x}}tail" }
  custom_status: fail.Status
  text.render_with(&custom_status, writer, &seam, fields[..], custom)
  check(custom_status.failure.kind == fail.Kind.Unsupported && custom_status.failure.native == -73)
  check(render(0, writer, nil, fields[..]).kind == fail.Kind.InvalidInput)
  missing: fail.Status
  text.render_with(&missing, writer, &empty, fields[..], nil)
  check(missing.failure.kind == fail.Kind.InvalidInput)
}
'''

# Nonempty literals retain an arena copy; storage exhaustion must panic rather
# than return a portable parse failure. Keep each wrapper in its own process.
PANIC_SOURCE = r'''use template "std/PACKAGE/template"
use mem "std/mem"
use "std/fail"
fn main() {
  status: fail.Status
  storage: [1 + mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(storage[..])
  arena = mem.arena_from_buffer(arena.data[..mem.ArenaHeader + 1])
  _ = template.parse(arena, &status, "ab")
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
