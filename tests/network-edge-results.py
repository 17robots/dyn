#!/usr/bin/env python3
"""Public HTTP/WebSocket parser goldens and portable/native result contracts."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
if sys.platform not in ('linux', 'darwin', 'win32'):
    print('SKIP network edge results: unsupported native host')
    raise SystemExit(0)

SOURCE = r'''use http "std/net/http"
use ws "std/net/websocket"
use io "std/io"
use parse "std/parse"
// A failure golden: Invalid at offset.
fn malformed_at(err: parse.ParseErr, at: usize) {
  case err {
    .Invalid(offset) => { if offset != at { #panic("parser offset golden") } }
    _ => { #panic("parser kind golden") }
  }
}
fn head(input: []const u8, response: bool, offset: usize) {
  if response {
    _ = http.parse_response(input) catch err {
      malformed_at(err, offset)
      return
    }
  } else {
    _ = http.parse_request(input) catch err {
      malformed_at(err, offset)
      return
    }
  }
  #panic("malformed head accepted")
}
fn url_at(input: []const u8, offset: usize) {
  _ = http.parse_url(input) catch err {
    malformed_at(err, offset)
    return
  }
  #panic("malformed URL accepted")
}
fn frame_at(input: []const u8, offset: usize) {
  _ = ws.parse_frame(input) catch err {
    malformed_at(err, offset)
    return
  }
  #panic("malformed frame accepted")
}
fn frame(input: []const u8) ws.WebSocketFrame {
  return ws.parse_frame(input) catch { #panic("frame") }
}
struct Trace { calls: usize, native: isize }
fn typed_handler(response: *http.Response, request: *const http.Request, state: *Trace) !io.IoErr {
}
fn read(data: rawptr, destination: []u8) usize!io.IoErr {
  trace := #cast(*Trace, data)
  trace.calls += 1
  fail .System(trace.native)
}
fn write(data: rawptr, source: []const u8) usize!io.IoErr {
  trace := #cast(*Trace, data)
  trace.calls += 1
  fail .System(trace.native)
}
fn invalid(err: io.IoErr) bool {
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
fn native(err: io.IoErr, trace: *const Trace) bool {
  case err {
    .System(code) => { return code == trace.native }
    _ => { return false }
  }
}
fn receive_err(server: *http.Server) io.IoErr {
  _ = http.receive(server) catch err { return err }
  #panic("receive unexpectedly succeeded")
}
fn event_err(state: *ws.WebSocketMessageState, message: []u8, control: []u8, frame: ws.WebSocketFrame) io.IoErr {
  _ = ws.receive(state, message, control, frame) catch err { return err }
  #panic("ws.receive unexpectedly succeeded")
}
fn upgrade_request_err(request: []const u8) io.IoErr {
  _ = ws.validate_upgrade_request(request) catch err { return err }
  #panic("upgrade request unexpectedly accepted")
}
fn upgrade_response_err(response: []const u8) io.IoErr {
  ws.validate_upgrade_response(response, "") catch err { return err }
  #panic("upgrade response unexpectedly accepted")
}
fn add_err(router: *http.Routes<Trace>, pattern: []const u8, handler: fn(*http.Response, *const http.Request, *Trace) !io.IoErr) io.IoErr {
  http.add(router, "GET", pattern, handler) catch err { return err }
  #panic("route unexpectedly added")
}
fn socket_receive_err(socket: *ws.WebSocketConnection) io.IoErr {
  _ = ws.connection_receive(socket) catch err { return err }
  #panic("connection_receive unexpectedly succeeded")
}
fn ping_err(socket: *ws.WebSocketConnection) io.IoErr {
  ws.connection_ping(socket, "", 0) catch err { return err }
  #panic("connection_ping unexpectedly succeeded")
}
fn send_err(socket: *ws.WebSocketConnection) io.IoErr {
  ws.connection_send(socket, 1, "x", true, 1) catch err { return err }
  #panic("connection_send unexpectedly succeeded")
}
fn close_err(socket: *ws.WebSocketConnection) io.IoErr {
  ws.connection_close(socket, "", 0) catch err { return err }
  #panic("connection_close unexpectedly succeeded")
}
fn main() {
  head("GET / HTTP/1.1\r\nBad Header: x\r\n\r\n", false, 19)
  head("GET / HTTP/1.1\r\nContent-Length: 1x\r\n\r\n", false, 33)
  head("GET / HTTP/2.0\r\n\r\n", false, 11)
  head("GET / HTTP/1.1\r\nTransfer-Encoding: chunks\r\n\r\n", false, 35)
  head("HTTP/1.1 200 OK\r\nTransfer-Encoding: gzip\r\n\r\n", true, 36)
  head("HTTP/1.1 2xx Bad\r\n\r\n", true, 10)
  head("HTTP/1.1 200 OK\r\nBad Header: x\r\n\r\n", true, 20)
  url_at("http://host:8x/path", 13)
  url_at("http://user@host/path", 11)
  url_at("http://host:0/path", 12)
  _ = http.parse_request("GET / HTTP/1.1\r\n\r\n") catch { #panic("request success") }
  _ = http.parse_response("HTTP/1.1 200 OK\r\n\r\n") catch { #panic("response success") }
  _ = http.parse_url("http://host/path") catch { #panic("URL success") }

  malformed: [4]u8 = [129, 126, 0, 1]
  frame_at(malformed[..], 2)
  // Part of a frame is no failure: complete is false.
  for size in 0..4 {
    if frame(malformed[..size]).complete { #panic("partial frame") }
  }
  reserved: [2]u8 = [193, 0]
  frame_at(reserved[..], 0)
  masked: [3]u8 = [129, 128, 0]
  partial := frame(masked[..])
  if partial.complete { #panic("partial mask") }
  valid: [2]u8 = [129, 0]
  whole := frame(valid[..])
  if !whole.complete || whole.consumed != 2 { #panic("frame success metadata") }
  state := ws.message_state(false)
  message: [32]u8
  control: [125]u8
  event := ws.receive(&state, message[..], control[..], whole) catch { #panic("event") }
  if event.detail != ws.WebSocketEventKind.Ready { #panic("event classification") }
  if !invalid(event_err(&state, message[..], control[..], partial)) { #panic("event metadata") }

  if !invalid(upgrade_request_err("GET / HTTP/1.1\r\nBad Header: x\r\n\r\n")) { #panic("upgrade head") }
  if !invalid(upgrade_request_err("GET / HTTP/1.1\r\n\r\n")) { #panic("upgrade fields") }
  if !invalid(upgrade_response_err("HTTP/1.1 2xx Bad\r\n\r\n")) { #panic("upgrade response head") }
  if !invalid(upgrade_response_err("HTTP/1.1 200 OK\r\n\r\n")) { #panic("upgrade metadata") }
  ws.validate_upgrade_response("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n", "dGhlIHNhbXBsZSBub25jZQ==") catch { #panic("upgrade success metadata") }

  routes: [1]http.TypedRoute<Trace>
  route_state := Trace{}
  router := http.typed_routes(routes[..], &route_state)
  if !invalid(add_err(&router, "/", nil)) || router.count != 0 { #panic("invalid route result") }
  http.add(&router, "GET", "/", typed_handler) catch { #panic("add route") }
  if router.count != 1 { #panic("route success result") }
  if !capacity(add_err(&router, "/other", typed_handler)) || router.count != 1 { #panic("route capacity result") }

  for code in [0, -73] {
    trace := Trace{ native: #cast(isize, code) }
    reader := io.Reader{ data: &trace, read: read }
    writer := io.Writer{ data: &trace, write: write }
    storage: [128]u8
    server := http.server(reader, writer, storage[..])
    if !native(receive_err(&server), &trace) { #panic("HTTP native metadata") }
    if !invalid(receive_err(&server)) { #panic("failed state") }
    if trace.calls != 1 { #panic("HTTP native replay") }
    trace.calls = 0
    frames: [32]u8
    socket := ws.connection(reader, writer, frames[..], message[..], control[..], true)
    if !native(socket_receive_err(&socket), &trace) { #panic("WS native read") }
    if trace.calls != 1 { #panic("WS native read metadata") }
    if !invalid(ping_err(&socket)) { #panic("failed state") }
    if trace.calls != 1 { #panic("WS native read replay") }
    socket = ws.connection(reader, writer, frames[..], message[..], control[..], true)
    if !native(send_err(&socket), &trace) { #panic("WS native write") }
    if trace.calls != 2 { #panic("WS native write metadata") }
    if !invalid(close_err(&socket)) { #panic("failed state") }
    if trace.calls != 2 { #panic("WS native write replay") }
  }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-network-edge-results-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    for mode in ('--debug', '--release'):
        output = project / ('program.exe' if os.name == 'nt' else 'program')
        subprocess.run([str(DYN), 'build', str(project), mode, '--no-cache', '--quiet',
                        '--output', str(output)], env=dict(os.environ, DYN_SDK=str(ROOT)),
                       check=True, timeout=90)
        subprocess.run([str(output)], check=True, timeout=10)
print('PASS public network parser goldens, failure metadata and native zero/nonzero (debug/release)')
