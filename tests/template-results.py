#!/usr/bin/env python3
"""Self-contained portable template result contracts, debug and release."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build' / ('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve()
SOURCE = r'''use "std/text/template" text
use "std/html/template" html
use "std/io" io
use "std/mem" mem
use "std/errors" errors
use "std/bytes" bytes
fn check(ok: bool) { if !ok { #panic("template results") } }
struct Sink { calls: usize, code: isize }
fn fail(data: rawptr, source: []const u8) io.Result {
  state := #cast(*Sink, data)
  state.calls += 1
  return io.Result{ transferred: 1, kind: errors.Kind.Capacity, error: state.code, status: io.Status.Error }
}
fn custom(destination: io.Writer, value: []const u8) text.RenderResult {
  return text.RenderResult{ kind: errors.Kind.Unsupported, error: -73, detail: text.ErrorKind.OutOfMemory, offset: 97 }
}
fn main() {
  storage: [4096 + mem.ArenaBufferOverhead]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  pzero: text.ParseResult
  rzero: html.RenderResult
  check(!pzero.ok && pzero.kind == errors.Kind.None && pzero.error == 0 && pzero.detail == text.ErrorKind.None && pzero.offset == 0 && #len(pzero.value.source) == 0)
  check(!rzero.ok && rzero.kind == errors.Kind.None && rzero.error == 0 && rzero.detail == html.ErrorKind.None && rzero.offset == 0)
  empty: text.Template
  writer: io.Writer
  fields: [1]text.Field = [text.Field{ name: "x", value: "<&>\"'" }]
  ready := text.render(writer, &empty, fields[..])
  check(ready.ok && ready.kind == errors.Kind.None && ready.error == 0 && ready.detail == text.ErrorKind.None && ready.offset == 0)
  check(html.render(writer, &empty, fields[..]).ok)
  for mode in 0..2 {
    // Validation and empty input need no storage, even in a full fixed arena.
    tiny_storage: [1 + mem.ArenaBufferOverhead]u8 = []
    tiny := mem.arena_from_buffer(tiny_storage[..])
    tiny = mem.arena_from_buffer(tiny.data[..mem.ArenaHeader + 1])
    _ = mem.arena_push(tiny, 1, 1)
    tiny_mark := mem.arena_mark(tiny)
    tiny_result := text.ParseResult{}
    if mode == 0 { tiny_result = text.parse(tiny, "") } else { tiny_result = html.parse(tiny, "") }
    check(tiny_result.ok && #len(tiny_result.value.source) == 0 && mem.arena_mark(tiny) == tiny_mark)
    if mode == 0 { tiny_result = text.parse(tiny, "ab{{ }}") } else { tiny_result = html.parse(tiny, "ab{{ }}") }
    check(!tiny_result.ok && tiny_result.kind == errors.Kind.InvalidInput && tiny_result.error == 0 && tiny_result.detail == text.ErrorKind.Syntax && tiny_result.offset == 2 && #len(tiny_result.value.source) == 0 && mem.arena_mark(tiny) == tiny_mark)
    mark := mem.arena_mark(arena)
    parsed := text.ParseResult{}
    if mode == 0 { parsed = text.parse(arena, "") } else { parsed = html.parse(arena, "") }
    check(parsed.ok && #len(parsed.value.source) == 0 && parsed.kind == errors.Kind.None && parsed.error == 0 && parsed.detail == text.ErrorKind.None && parsed.offset == 0 && mem.arena_mark(arena) == mark)
    invalid: [3][]const u8 = ["{{", "ab{{ }}", "a{{x!}}"]
    offsets: [3]usize = [0, 2, 1]
    for i in 0..3 {
      if mode == 0 { parsed = text.parse(arena, invalid[i]) } else { parsed = html.parse(arena, invalid[i]) }
      check(!parsed.ok && parsed.kind == errors.Kind.InvalidInput && parsed.error == 0 && parsed.detail == text.ErrorKind.Syntax && parsed.offset == offsets[i] && #len(parsed.value.source) == 0 && mem.arena_mark(arena) == mark)
    }
    source: [10]u8 = ['<','b','>','{','{','x','}','}','!','!']
    if mode == 0 { parsed = text.parse(arena, source[..]) } else { parsed = html.parse(arena, source[..]) }
    check(parsed.ok && parsed.kind == errors.Kind.None && parsed.error == 0 && parsed.detail == text.ErrorKind.None && parsed.offset == 0)
    source[0] = '?'
    check(parsed.value.source[0] == '<') // parse owns an arena copy.
    output: [128]u8 = []
    buffer := io.buffer_writer(output[..])
    rendered := text.RenderResult{}
    if mode == 0 { rendered = text.render(io.buffer_writer_adapter(&buffer), &parsed.value, fields[..]) } else { rendered = html.render(io.buffer_writer_adapter(&buffer), &parsed.value, fields[..]) }
    check(rendered.ok && rendered.kind == errors.Kind.None && rendered.error == 0 && rendered.detail == text.ErrorKind.None && rendered.offset == 0)
    if mode == 0 { check(bytes.equal(io.buffer_writer_bytes(&buffer), "<b><&>\"'!!")) } else { check(bytes.equal(io.buffer_writer_bytes(&buffer), "<b>&lt;&amp;&gt;&quot;&#39;!!")) }
    for code in [0, -91] {
      sink := Sink{ code: code }
      failing := io.Writer{ data: &sink, write: fail }
      if mode == 0 { rendered = text.render(failing, &parsed.value, fields[..]) } else { rendered = html.render(failing, &parsed.value, fields[..]) }
      check(!rendered.ok && rendered.kind == errors.Kind.Capacity && rendered.error == #cast(isize, code) && rendered.detail == text.ErrorKind.Io && rendered.offset == 1 && sink.calls == 1)
      field_only := text.Template{ source: "{{x}}tail" }
      sink.calls = 0
      if mode == 0 { rendered = text.render(failing, &field_only, fields[..]) } else { rendered = html.render(failing, &field_only, fields[..]) }
      check(!rendered.ok && rendered.kind == errors.Kind.Capacity && rendered.error == #cast(isize, code) && rendered.detail == text.ErrorKind.Io && rendered.offset == 0 && sink.calls == 1)
    }
    mem.arena_rewind(arena, mark)
  }
  seam := text.Template{ source: "{{x}}tail" }
  unchanged := text.render_with(writer, &seam, fields[..], custom)
  check(!unchanged.ok && unchanged.kind == errors.Kind.Unsupported && unchanged.error == -73 && unchanged.detail == text.ErrorKind.OutOfMemory && unchanged.offset == 97)
  check(text.render(writer, nil, fields[..]).kind == errors.Kind.InvalidInput)
  check(text.render_with(writer, &empty, fields[..], nil).kind == errors.Kind.InvalidInput)
}
'''

# Nonempty literals retain an arena copy; storage exhaustion must panic rather
# than return a portable parse failure. Keep each wrapper in its own process.
PANIC_SOURCE = r'''use "std/PACKAGE/template" template
use "std/mem" mem
fn main() {
  storage: [1 + mem.ArenaBufferOverhead]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  arena = mem.arena_from_buffer(arena.data[..mem.ArenaHeader + 1])
  _ = template.parse(arena, "ab")
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
