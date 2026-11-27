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
use io "std/io"
use http "std/net/http"
// A writer that fails its fail-th call with System(code), counting calls.
struct Sink { calls: usize, fail: usize, code: isize, partial: bool }
fn write(raw: rawptr, source: []const u8) usize!io.IoErr {
  s := #cast(*Sink, raw)
  s.calls += 1
  if s.calls == s.fail { fail .System(s.code) }
  count := source.len
  if s.partial && count > 1 { count = 1 }
  return count
}
struct Feed { calls: usize, wire: []const u8, code: isize, fail: bool, delivered: bool }
// The wire once, then the end: a stream ends with a read that returns 0.
fn read(raw: rawptr, destination: []u8) usize!io.IoErr {
  f := #cast(*Feed, raw)
  f.calls += 1
  if f.fail { fail .System(f.code) }
  if f.delivered { return 0 }
  f.delivered = true
  count := f.wire.len
  if count > destination.len { count = destination.len }
  for i in 0..count { destination[i] = f.wire[i] }
  return count
}
fn check(ok: bool, message: []const u8) { if !ok { #panic(message) } }
// The writer's own failure, native code included.
fn system(err: io.IoErr, code: isize) bool {
  case err {
    .System(native) => { return native == code }
    _ => { return false }
  }
}
// What http reports once a response, body or server has finished.
fn finished(err: io.IoErr) bool {
  case err {
    .InvalidInput => { return true }
    _ => { return false }
  }
}
fn capacity(err: io.IoErr) bool {
  case err {
    .Capacity => { return true }
    _ => { return false }
  }
}
fn respond_err(response: *http.Response, body: []const u8) io.IoErr {
  http.respond(response, body, http.ResponseOptions{}) catch err { return err }
  #panic("respond unexpectedly succeeded")
}
fn stream_err(response: *http.Response) io.IoErr {
  _ = http.respond_stream(response, http.ResponseOptions{}) catch err { return err }
  #panic("respond_stream unexpectedly succeeded")
}
fn write_err(writer: io.Writer, text: []const u8) io.IoErr {
  io.write(writer, text) catch err { return err }
  #panic("body write unexpectedly succeeded")
}
fn finish_err(body: *http.Body) io.IoErr {
  http.body_finish(body) catch err { return err }
  #panic("body_finish unexpectedly succeeded")
}
fn receive_err(state: *http.Server) io.IoErr {
  _ = http.receive(state) catch err { return err }
  #panic("receive unexpectedly succeeded")
}
fn main() {
  for native in [0, -73] {
    code := #cast(isize, native)
    // Head and small body leave in one write; a failure finishes the response.
    for segment in 1..2 {
      sink := Sink{ fail: #cast(usize, segment), code: code }
      response := http.Response{ output: io.Writer{ data: &sink, write: write } }
      check(system(respond_err(&response, "body"), code), "first HTTP failure")
      calls := sink.calls
      check(finished(respond_err(&response, "")), "respond after a failure")
      check(finished(stream_err(&response)), "stream after a failure")
      check(sink.calls == calls, "response retried IO")
    }
    // A chunk that fails finishes the body: later writes and the finish fail
    // without writing.
    for segment in 1..4 {
      sink := Sink{}
      response := http.Response{ output: io.Writer{ data: &sink, write: write } }
      body := http.respond_stream(&response, http.ResponseOptions{}) catch { #panic("open body") }
      sink.fail = sink.calls + #cast(usize, segment)
      sink.code = code
      writer := http.body_writer(&body)
      if segment == 1 {
        check(system(write_err(writer, "abc"), code), "first body failure")
      } else {
        io.write(writer, "abc") catch { #panic("early failure") }
        if segment == 2 {
          check(system(finish_err(&body), code), "finish failure")
        } else {
          // Partial writes in a later body chunk.
          sink.partial = true
          check(system(write_err(writer, "later"), code), "partial body failure")
        }
      }
      calls := sink.calls
      check(finished(write_err(writer, "x")), "write after a failure")
      check(finished(finish_err(&body)), "finish after a failure")
      check(sink.calls == calls, "body retried IO")
    }
    // A failed receive leaves the server failed: later receives read nothing.
    feed := Feed{ fail: true, code: code }
    sink := Sink{}
    storage: [128]u8
    state := http.server(io.Reader{ data: &feed, read: read }, io.Writer{ data: &sink, write: write }, storage[..])
    check(system(receive_err(&state), code), "receive IO failure")
    check(finished(receive_err(&state)), "receive after a failure")
    check(feed.calls == 1, "receive IO replay")
    state = http.server(io.Reader{ data: &feed, read: read }, io.Writer{ data: &sink, write: write }, storage[..])
    _ = receive_err(&state)
    check(feed.calls == 2, "constructor reset")
  }
  for wire in ["bad\r\n\r\n", "GET / HTTP/1.1\r\nContent-Length: 999\r\n\r\n", "GET / HTTP/1.1\r\n"] {
    feed := Feed{ wire: wire }
    sink := Sink{}
    storage: [64]u8
    state := http.server(io.Reader{ data: &feed, read: read }, io.Writer{ data: &sink, write: write }, storage[..])
    _ = receive_err(&state)
    calls := feed.calls
    check(finished(receive_err(&state)), "receive after a terminal request")
    check(feed.calls == calls, "receive terminal replay")
  }
  for wire in ["", "GET / HTTP/1.1\r\n\r\n"] {
    feed := Feed{ wire: wire }
    sink := Sink{}
    storage: [64]u8
    state := http.server(io.Reader{ data: &feed, read: read }, io.Writer{ data: &sink, write: write }, storage[..])
    received := http.receive(&state) catch { #panic("clean end") }
    if !received.ended {
      received = http.receive(&state) catch { #panic("clean end") }
    }
    check(received.ended, "clean end")
  }
  feed := Feed{ wire: "GET / HTTP/1.1\r\n\r\n" }
  sink_zero := Sink{}
  empty: [0]u8
  small := http.server(io.Reader{ data: &feed, read: read }, io.Writer{ data: &sink_zero, write: write }, empty[..])
  check(capacity(receive_err(&small)) && feed.calls == 0, "empty capacity IO")
  zero := http.Server{}
  check(finished(receive_err(&zero)), "zero server")
  response := http.Response{}
  check(finished(respond_err(&response, "")), "zero response")
  body := http.Body{}
  writer := http.body_writer(&body)
  _ = write_err(writer, "x")
  _ = finish_err(&body)
  // Successful partial writes remain usable.
  sink := Sink{ partial: true }
  response = http.Response{ output: io.Writer{ data: &sink, write: write } }
  opened := http.respond_stream(&response, http.ResponseOptions{}) catch { #panic("partial open") }
  writer = http.body_writer(&opened)
  io.write(writer, "abc") catch { #panic("partial write") }
  http.body_finish(&opened) catch { #panic("partial finish") }
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
