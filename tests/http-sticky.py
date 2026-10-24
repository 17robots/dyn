#!/usr/bin/env python3
"""Independent callback counters prove HTTP failures remain sticky, including native zero."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
SOURCE = r'''
use "std/io" io
use "std/errors" errors
use "std/net/http" http
struct Sink { calls: usize, fail: usize, code: isize, partial: bool }
fn write(raw: rawptr, source: []const u8) io.Result {
  s := #cast(*Sink, raw)
  s.calls += 1
  if s.calls == s.fail { return io.Result{ transferred: 1, error: s.code, kind: errors.Kind.InvalidInput, status: io.Status.Error } }
  count := #len(source)
  if s.partial && count > 1 { count = 1 }
  return io.Result{ transferred: count }
}
struct Feed { calls: usize, wire: []const u8, code: isize, fail: bool }
fn read(raw: rawptr, dest: []u8) io.Result {
  f := #cast(*Feed, raw)
  f.calls += 1
  if f.fail { return io.Result{ error: f.code, status: io.Status.Error } }
  count := #len(f.wire)
  if count > #len(dest) { count = #len(dest) }
  for i in 0..count { dest[i] = f.wire[i] }
  return io.Result{ transferred: count, status: io.Status.End }
}
fn same(r: http.Result, code: isize) {
  if r.ok || r.detail != http.ErrorKind.Io || r.error != code { #panic("first HTTP error") }
}
fn main() {
  for native in [0, -73] {
    code := #cast(isize, native)
    // Nine fixed-length header segments followed by body; each can fail independently.
    for segment in 1..11 {
      sink := Sink{ fail: #cast(usize, segment), code: code }
      response := http.Response{ output: io.Writer{ data: &sink, write: &write } }
      first := http.respond(&response, "body", http.ResponseOptions{})
      same(first, code)
      calls := sink.calls
      same(http.respond(&response, "", http.ResponseOptions{}), code)
      again := http.respond_stream(&response, http.ResponseOptions{})
      same(again.result, code)
      if sink.calls != calls { #panic("response retried IO") }
    }
    for segment in 1..9 {
      sink := Sink{ fail: #cast(usize, segment), code: code }
      response := http.Response{ output: io.Writer{ data: &sink, write: &write } }
      opened := http.respond_stream(&response, http.ResponseOptions{})
      same(opened.result, code)
      calls := sink.calls
      writer := http.body_writer(&opened.body)
      replay := writer.write(writer.data, "")
      if replay.status != io.Status.Error || replay.error != code || replay.kind != errors.Kind.InvalidInput { #panic("header stream metadata") }
      same(http.body_finish(&opened.body), code)
      if sink.calls != calls { #panic("header retry") }
    }
    for segment in 1..6 {
      sink := Sink{}
      response := http.Response{ output: io.Writer{ data: &sink, write: &write } }
      opened := http.respond_stream(&response, http.ResponseOptions{})
      if !opened.ok { #panic("open body") }
      sink.fail = sink.calls + #cast(usize, segment)
      sink.code = code
      writer := http.body_writer(&opened.body)
      first := writer.write(writer.data, "abc")
      if segment == 5 {
        if first.status == io.Status.Error { #panic("early failure") }
        same(http.body_finish(&opened.body), code)
      } else if segment == 6 {
        // Partial writes in a later body chunk.
        sink.partial = true
        first = writer.write(writer.data, "later")
      }
      if segment != 5 && (first.status != io.Status.Error || first.error != code || first.kind != errors.Kind.InvalidInput) { #panic("stream error metadata") }
      calls := sink.calls
      replay := writer.write(writer.data, "")
      if replay.status != io.Status.Error || replay.error != code { #panic("empty callback replay") }
      replay = io.write(writer, "x")
      if replay.status != io.Status.Error || replay.error != code || replay.kind != errors.Kind.InvalidInput || replay.transferred != 0 { #panic("short replay") }
      same(http.body_finish(&opened.body), code)
      same(http.body_abort(&opened.body), code)
      if sink.calls != calls { #panic("body retried IO") }
    }
    feed := Feed{ fail: true, code: code }
    sink := Sink{}
    storage: [128]u8 = []
    state := http.server(io.Reader{ data: &feed, read: &read }, io.Writer{ data: &sink, write: &write }, storage[..])
    first := http.receive(&state)
    again := http.receive(&state)
    if first.detail != http.ErrorKind.Io || again.error != code || feed.calls != 1 { #panic("receive IO replay") }
    state = http.server(io.Reader{ data: &feed, read: &read }, io.Writer{ data: &sink, write: &write }, storage[..])
    _ = http.receive(&state)
    if feed.calls != 2 { #panic("constructor reset") }
  }
  for wire in ["bad\r\n\r\n", "GET / HTTP/1.1\r\nContent-Length: 999\r\n\r\n", "", "GET / HTTP/1.1\r\n", "GET / HTTP/1.1\r\n\r\n"] {
    feed := Feed{ wire: wire }
    sink := Sink{}
    storage: [64]u8 = []
    state := http.server(io.Reader{ data: &feed, read: &read }, io.Writer{ data: &sink, write: &write }, storage[..])
    first := http.receive(&state)
    if first.ok { first = http.receive(&state) }
    calls := feed.calls
    again := http.receive(&state)
    if first.ok || again.error != first.error || feed.calls != calls { #panic("receive terminal replay") }
  }
  feed := Feed{ wire: "GET / HTTP/1.1\r\n\r\n" }
  sink_zero := Sink{}
  empty: [0]u8 = []
  capacity := http.server(io.Reader{ data: &feed, read: &read }, io.Writer{ data: &sink_zero, write: &write }, empty[..])
  if http.receive(&capacity).detail != http.ErrorKind.Capacity || http.receive(&capacity).detail != http.ErrorKind.Capacity || feed.calls != 0 { #panic("empty capacity IO") }
  zero := http.Server{}
  if http.receive(&zero).detail != http.ErrorKind.Invalid { #panic("zero server") }
  response := http.Response{}
  if http.respond(&response, "", http.ResponseOptions{}).detail != http.ErrorKind.Invalid { #panic("zero response") }
  body := http.Body{}
  writer := http.body_writer(&body)
  if writer.write(writer.data, "").status != io.Status.Error || http.body_abort(&body).ok || http.body_finish(&body).ok { #panic("zero body") }
  // Successful partial writes and empty callbacks remain usable.
  sink := Sink{ partial: true }
  response = http.Response{ output: io.Writer{ data: &sink, write: &write } }
  opened := http.respond_stream(&response, http.ResponseOptions{})
  writer = http.body_writer(&opened.body)
  if writer.write(writer.data, "").status == io.Status.Error || io.write_all(writer, "abc").transferred != 3 { #panic("partial success") }
  if !http.body_finish(&opened.body).ok { #panic("finish success") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-http-sticky-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    for mode in ('--debug', '--release'):
        binary = project / 'sticky'
        subprocess.run([str(DYN), 'build', str(project), mode, '--quiet', '--no-cache', '--output', str(binary)], env=dict(os.environ, DYN_SDK=str(ROOT)), check=True, timeout=120)
        subprocess.run([str(binary)], check=True, timeout=15)
print('PASS HTTP sticky failures (debug/release)')
