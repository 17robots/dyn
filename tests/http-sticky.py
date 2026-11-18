#!/usr/bin/env python3
"""Independent callback counters prove HTTP failures remain sticky, including native zero."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
SOURCE = r'''
use "std/fail"
use "std/io" io
use "std/io" errors
use "std/net/http" http
struct Sink { calls: usize, fail: usize, code: isize, partial: bool }
fn write_transfer(raw: rawptr, source: []const u8) io.Transfer {
  s := #cast(*Sink, raw)
  s.calls += 1
  if s.calls == s.fail { return io.Transfer{ transferred: 1, failure: io.Failure{ kind: errors.Kind.InvalidInput, native: s.code } } }
  count := #len(source)
  if s.partial && count > 1 { count = 1 }
  return io.Transfer{ transferred: count }
}
fn write(data: rawptr, status: *fail.Status, source: []const u8) usize {
  return io.from_transfer(status, write_transfer(data, source), "write", "")
}
struct Feed { calls: usize, wire: []const u8, code: isize, fail: bool, delivered: bool }
// The wire once, then the end: a stream ends with a read that returns 0.
fn read_transfer(raw: rawptr, dest: []u8) io.Transfer {
  f := #cast(*Feed, raw)
  f.calls += 1
  if f.fail { return io.Transfer{ failure: io.Failure{ kind: io.Kind.System, native: f.code } } }
  if f.delivered { return io.Transfer{ status: io.Status.End } }
  f.delivered = true
  count := #len(f.wire)
  if count > #len(dest) { count = #len(dest) }
  for i in 0..count { dest[i] = f.wire[i] }
  return io.Transfer{ transferred: count, status: io.Status.End }
}
fn read(data: rawptr, status: *fail.Status, destination: []u8) usize {
  return io.from_transfer(status, read_transfer(data, destination), "read", "")
}
fn same(r: http.Result, code: isize) {
  if !io.failed(r.failure) || r.detail != http.ErrorKind.Io || r.failure.native != code { #panic("first HTTP error") }
}
fn main() {
  for native in [0, -73] {
    code := #cast(isize, native)
    // Head and small body leave in one write.
    for segment in 1..2 {
      sink := Sink{ fail: #cast(usize, segment), code: code }
      response := http.Response{ output: io.Writer{ data: &sink, write: write } }
      first := http.respond(&response, "body", http.ResponseOptions{})
      same(first, code)
      calls := sink.calls
      same(http.respond(&response, "", http.ResponseOptions{}), code)
      again := http.respond_stream(&response, http.ResponseOptions{})
      same(again.result, code)
      if sink.calls != calls { #panic("response retried IO") }
    }
    // The stream head leaves in one write.
    for segment in 1..2 {
      sink := Sink{ fail: #cast(usize, segment), code: code }
      response := http.Response{ output: io.Writer{ data: &sink, write: write } }
      opened := http.respond_stream(&response, http.ResponseOptions{})
      same(opened.result, code)
      calls := sink.calls
      writer := http.body_writer(&opened.body)
      replay_status_1: fail.Status
      _ = writer.write(writer.data, &replay_status_1, "")
      replay := io.Transfer{ failure: io.Failure{ kind: replay_status_1.failure.kind, native: replay_status_1.failure.native } }
      if !io.failed(replay.failure) || replay.failure.native != code || replay.failure.kind != errors.Kind.InvalidInput { #panic("header stream metadata") }
      same(http.body_finish(&opened.body), code)
      if sink.calls != calls { #panic("header retry") }
    }
    // A small chunk is one write: segment 1 fails it, 2 fails the finish, 3
    // fails partway through a later chunk written one byte per call.
    for segment in 1..4 {
      sink := Sink{}
      response := http.Response{ output: io.Writer{ data: &sink, write: write } }
      opened := http.respond_stream(&response, http.ResponseOptions{})
      if io.failed(opened.failure) { #panic("open body") }
      sink.fail = sink.calls + #cast(usize, segment)
      sink.code = code
      writer := http.body_writer(&opened.body)
      first_status_2: fail.Status
      _ = writer.write(writer.data, &first_status_2, "abc")
      first := io.Transfer{ failure: io.Failure{ kind: first_status_2.failure.kind, native: first_status_2.failure.native } }
      if segment == 2 {
        if io.failed(first.failure) { #panic("early failure") }
        same(http.body_finish(&opened.body), code)
      } else if segment == 3 {
        // Partial writes in a later body chunk.
        sink.partial = true
        first_status_3: fail.Status
        _ = writer.write(writer.data, &first_status_3, "later")
        first = io.Transfer{ failure: io.Failure{ kind: first_status_3.failure.kind, native: first_status_3.failure.native } }
      }
      if segment != 2 && (!io.failed(first.failure) || first.failure.native != code || first.failure.kind != errors.Kind.InvalidInput) { #panic("stream error metadata") }
      calls := sink.calls
      replay_status_4: fail.Status
      _ = writer.write(writer.data, &replay_status_4, "")
      replay := io.Transfer{ failure: io.Failure{ kind: replay_status_4.failure.kind, native: replay_status_4.failure.native } }
      if !io.failed(replay.failure) || replay.failure.native != code { #panic("empty callback replay") }
      replay = io.write_transfer(writer, "x")
      if !io.failed(replay.failure) || replay.failure.native != code || replay.failure.kind != errors.Kind.InvalidInput || replay.transferred != 0 { #panic("short replay") }
      same(http.body_finish(&opened.body), code)
      same(http.body_abort(&opened.body), code)
      if sink.calls != calls { #panic("body retried IO") }
    }
    feed := Feed{ fail: true, code: code }
    sink := Sink{}
    storage: [128]u8
    state := http.server(io.Reader{ data: &feed, read: read }, io.Writer{ data: &sink, write: write }, storage[..])
    first := http.receive(&state)
    again := http.receive(&state)
    if first.detail != http.ErrorKind.Io || again.failure.native != code || feed.calls != 1 { #panic("receive IO replay") }
    state = http.server(io.Reader{ data: &feed, read: read }, io.Writer{ data: &sink, write: write }, storage[..])
    _ = http.receive(&state)
    if feed.calls != 2 { #panic("constructor reset") }
  }
  for wire in ["bad\r\n\r\n", "GET / HTTP/1.1\r\nContent-Length: 999\r\n\r\n", "", "GET / HTTP/1.1\r\n", "GET / HTTP/1.1\r\n\r\n"] {
    feed := Feed{ wire: wire }
    sink := Sink{}
    storage: [64]u8
    state := http.server(io.Reader{ data: &feed, read: read }, io.Writer{ data: &sink, write: write }, storage[..])
    first := http.receive(&state)
    if first.detail == http.ErrorKind.None { first = http.receive(&state) }
    calls := feed.calls
    again := http.receive(&state)
    if first.detail == http.ErrorKind.None || again.failure.native != first.failure.native || feed.calls != calls { #panic("receive terminal replay") }
  }
  feed := Feed{ wire: "GET / HTTP/1.1\r\n\r\n" }
  sink_zero := Sink{}
  empty: [0]u8
  capacity := http.server(io.Reader{ data: &feed, read: read }, io.Writer{ data: &sink_zero, write: write }, empty[..])
  if http.receive(&capacity).detail != http.ErrorKind.Capacity || http.receive(&capacity).detail != http.ErrorKind.Capacity || feed.calls != 0 { #panic("empty capacity IO") }
  zero := http.Server{}
  if http.receive(&zero).detail != http.ErrorKind.Invalid { #panic("zero server") }
  response := http.Response{}
  if http.respond(&response, "", http.ResponseOptions{}).detail != http.ErrorKind.Invalid { #panic("zero response") }
  body := http.Body{}
  writer := http.body_writer(&body)
  zero_write: fail.Status
  _ = writer.write(writer.data, &zero_write, "")
  if !zero_write.failed || !io.failed(http.body_abort(&body).failure) || !io.failed(http.body_finish(&body).failure) { #panic("zero body") }
  // Successful partial writes and empty callbacks remain usable.
  sink := Sink{ partial: true }
  response = http.Response{ output: io.Writer{ data: &sink, write: write } }
  opened := http.respond_stream(&response, http.ResponseOptions{})
  writer = http.body_writer(&opened.body)
  empty_write: fail.Status
  _ = writer.write(writer.data, &empty_write, "")
  if empty_write.failed || io.write_transfer(writer, "abc").transferred != 3 { #panic("partial success") }
  if io.failed(http.body_finish(&opened.body).failure) { #panic("finish success") }
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
