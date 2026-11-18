#!/usr/bin/env python3
"""Independent callback counters prove a failed response, body or server stays
finished, keeping the native code, including native zero."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
SOURCE = r'''
use "std/fail"
use "std/io" io
use "std/net/http" http
// A writer that fails its fail-th call with code, counting calls.
struct Sink { calls: usize, fail: usize, code: isize, partial: bool }
fn write(raw: rawptr, status: *fail.Status, source: []const u8) usize {
  s := #cast(*Sink, raw)
  s.calls += 1
  if s.calls == s.fail {
    failure := fail.make(fail.Kind.InvalidInput, "write", "", "sink failure")
    failure.native = s.code
    fail.set(status, failure)
    return 0
  }
  count := #len(source)
  if s.partial && count > 1 { count = 1 }
  return count
}
struct Feed { calls: usize, wire: []const u8, code: isize, fail: bool, delivered: bool }
// The wire once, then the end: a stream ends with a read that returns 0.
fn read(raw: rawptr, status: *fail.Status, destination: []u8) usize {
  f := #cast(*Feed, raw)
  f.calls += 1
  if f.fail {
    failure := fail.make(fail.Kind.System, "read", "", "feed failure")
    failure.native = f.code
    fail.set(status, failure)
    return 0
  }
  if f.delivered { return 0 }
  f.delivered = true
  count := #len(f.wire)
  if count > #len(destination) { count = #len(destination) }
  for i in 0..count { destination[i] = f.wire[i] }
  return count
}
fn sink_failure(status: *const fail.Status, code: isize) {
  if !status.failed || status.failure.kind != fail.Kind.InvalidInput || status.failure.native != code { #panic("first HTTP failure") }
}
fn finished(status: *const fail.Status) {
  if !status.failed || status.failure.kind != fail.Kind.InvalidState { #panic("finished after a failure") }
}
fn main() {
  for native in [0, -73] {
    code := #cast(isize, native)
    // Head and small body leave in one write; a failure finishes the response.
    for segment in 1..2 {
      sink := Sink{ fail: #cast(usize, segment), code: code }
      response := http.Response{ output: io.Writer{ data: &sink, write: write } }
      first: fail.Status
      http.respond(&first, &response, "body", http.ResponseOptions{})
      sink_failure(&first, code)
      calls := sink.calls
      again: fail.Status
      http.respond(&again, &response, "", http.ResponseOptions{})
      finished(&again)
      stream: fail.Status
      _ = http.respond_stream(&stream, &response, http.ResponseOptions{})
      finished(&stream)
      if sink.calls != calls { #panic("response retried IO") }
    }
    // A chunk that fails finishes the body: later writes and the finish fail
    // without writing.
    for segment in 1..4 {
      sink := Sink{}
      response := http.Response{ output: io.Writer{ data: &sink, write: write } }
      opened: fail.Status
      body := http.respond_stream(&opened, &response, http.ResponseOptions{})
      if opened.failed { #panic("open body") }
      sink.fail = sink.calls + #cast(usize, segment)
      sink.code = code
      writer := http.body_writer(&body)
      first: fail.Status
      io.write(&first, writer, "abc")
      if segment == 2 {
        if first.failed { #panic("early failure") }
        http.body_finish(&first, &body)
      } else if segment == 3 {
        // Partial writes in a later body chunk.
        sink.partial = true
        io.write(&first, writer, "later")
      }
      sink_failure(&first, code)
      calls := sink.calls
      replay: fail.Status
      io.write(&replay, writer, "x")
      finished(&replay)
      ended: fail.Status
      http.body_finish(&ended, &body)
      finished(&ended)
      if sink.calls != calls { #panic("body retried IO") }
    }
    // A failed receive leaves the server failed: later receives read nothing.
    feed := Feed{ fail: true, code: code }
    sink := Sink{}
    storage: [128]u8
    state := http.server(io.Reader{ data: &feed, read: read }, io.Writer{ data: &sink, write: write }, storage[..])
    first: fail.Status
    _ = http.receive(&first, &state)
    if !first.failed || first.failure.kind != fail.Kind.System || first.failure.native != code { #panic("receive IO failure") }
    again: fail.Status
    _ = http.receive(&again, &state)
    finished(&again)
    if feed.calls != 1 { #panic("receive IO replay") }
    state = http.server(io.Reader{ data: &feed, read: read }, io.Writer{ data: &sink, write: write }, storage[..])
    reset: fail.Status
    _ = http.receive(&reset, &state)
    if feed.calls != 2 { #panic("constructor reset") }
  }
  for wire in ["bad\r\n\r\n", "GET / HTTP/1.1\r\nContent-Length: 999\r\n\r\n", "GET / HTTP/1.1\r\n"] {
    feed := Feed{ wire: wire }
    sink := Sink{}
    storage: [64]u8
    state := http.server(io.Reader{ data: &feed, read: read }, io.Writer{ data: &sink, write: write }, storage[..])
    first: fail.Status
    _ = http.receive(&first, &state)
    if !first.failed { #panic("terminal receive") }
    calls := feed.calls
    again: fail.Status
    _ = http.receive(&again, &state)
    finished(&again)
    if feed.calls != calls { #panic("receive terminal replay") }
  }
  for wire in ["", "GET / HTTP/1.1\r\n\r\n"] {
    feed := Feed{ wire: wire }
    sink := Sink{}
    storage: [64]u8
    state := http.server(io.Reader{ data: &feed, read: read }, io.Writer{ data: &sink, write: write }, storage[..])
    status: fail.Status
    received := http.receive(&status, &state)
    if !received.ended {
      received = http.receive(&status, &state)
    }
    if status.failed || !received.ended { #panic("clean end") }
  }
  feed := Feed{ wire: "GET / HTTP/1.1\r\n\r\n" }
  sink_zero := Sink{}
  empty: [0]u8
  capacity := http.server(io.Reader{ data: &feed, read: read }, io.Writer{ data: &sink_zero, write: write }, empty[..])
  full: fail.Status
  _ = http.receive(&full, &capacity)
  if full.failure.kind != fail.Kind.Capacity || feed.calls != 0 { #panic("empty capacity IO") }
  zero := http.Server{}
  zero_status: fail.Status
  _ = http.receive(&zero_status, &zero)
  finished(&zero_status)
  response := http.Response{}
  zero_response: fail.Status
  http.respond(&zero_response, &response, "", http.ResponseOptions{})
  finished(&zero_response)
  body := http.Body{}
  writer := http.body_writer(&body)
  zero_write: fail.Status
  io.write(&zero_write, writer, "x")
  zero_finish: fail.Status
  http.body_finish(&zero_finish, &body)
  if !zero_write.failed || !zero_finish.failed { #panic("zero body") }
  // Successful partial writes remain usable.
  sink := Sink{ partial: true }
  response = http.Response{ output: io.Writer{ data: &sink, write: write } }
  status: fail.Status
  opened := http.respond_stream(&status, &response, http.ResponseOptions{})
  writer = http.body_writer(&opened)
  io.write(&status, writer, "abc")
  http.body_finish(&status, &opened)
  if status.failed { #panic("partial success") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-http-sticky-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    for mode in ('--debug', '--release'):
        binary = project / 'sticky'
        subprocess.run([str(DYN), 'build', str(project), mode, '--quiet', '--no-cache', '--output', str(binary)], env=dict(os.environ, DYN_SDK=str(ROOT)), check=True, timeout=120)
        subprocess.run([str(binary)], check=True, timeout=15)
print('PASS HTTP failures finish responses, bodies and servers (debug/release)')
