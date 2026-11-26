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
use "std/fail"
use io "std/io"
// A failure golden: InvalidInput at offset.
fn malformed_at(status: *const fail.Status, at: usize) {
  if !status.failed || status.failure.kind != fail.Kind.InvalidInput || status.failure.offset != at { #panic("parser metadata golden") }
}
fn head(input: []const u8, response: bool, offset: usize) {
  status: fail.Status
  if response {
    _ = http.parse_response(&status, input)
  } else {
    _ = http.parse_request(&status, input)
  }
  malformed_at(&status, offset)
}
fn url_at(input: []const u8, offset: usize) {
  status: fail.Status
  _ = http.parse_url(&status, input)
  malformed_at(&status, offset)
}
fn frame_at(input: []const u8, offset: usize) {
  status: fail.Status
  _ = ws.parse_frame(&status, input)
  malformed_at(&status, offset)
}
struct Trace { calls: usize, native: isize }
fn typed_handler(status: *fail.Status, response: *http.Response, request: *const http.Request, state: *Trace) {
}
fn denied(status: *fail.Status, operation: []const u8, trace: *Trace) {
  failure := fail.make(fail.Kind.PermissionDenied, operation, "", "")
  failure.native = trace.native
  fail.set(status, failure)
}
fn read(data: rawptr, destination: []u8) usize!io.IoErr {
  status: fail.Status
  count := read_status(data, &status, destination)
  try io.check_status(&status)
  return count
}
fn read_status(data: rawptr, status: *fail.Status, destination: []u8) usize {
  trace := #cast(*Trace, data)
  trace.calls += 1
  denied(status, "read", trace)
  return 0
}
fn write(data: rawptr, source: []const u8) usize!io.IoErr {
  status: fail.Status
  count := write_status(data, &status, source)
  try io.check_status(&status)
  return count
}
fn write_status(data: rawptr, status: *fail.Status, source: []const u8) usize {
  trace := #cast(*Trace, data)
  trace.calls += 1
  denied(status, "write", trace)
  return 0
}
fn denied_with(status: *const fail.Status, trace: *const Trace) {
  if !status.failed || status.failure.kind != fail.Kind.PermissionDenied || status.failure.has_offset { #panic("native metadata") }
}
fn finished(status: *const fail.Status) {
  if !status.failed || status.failure.kind != fail.Kind.InvalidState { #panic("failed state") }
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
  status: fail.Status
  _ = http.parse_request(&status, "GET / HTTP/1.1\r\n\r\n")
  _ = http.parse_response(&status, "HTTP/1.1 200 OK\r\n\r\n")
  _ = http.parse_url(&status, "http://host/path")
  if status.failed { #panic("success metadata") }

  malformed: [4]u8 = [129, 126, 0, 1]
  frame_at(malformed[..], 2)
  // Part of a frame is no failure: complete is false.
  for size in 0..4 {
    frame := ws.parse_frame(&status, malformed[..size])
    if status.failed || frame.complete { #panic("partial frame") }
  }
  reserved: [2]u8 = [193, 0]
  frame_at(reserved[..], 0)
  masked: [3]u8 = [129, 128, 0]
  partial := ws.parse_frame(&status, masked[..])
  if status.failed || partial.complete { #panic("partial mask") }
  valid: [2]u8 = [129, 0]
  frame := ws.parse_frame(&status, valid[..])
  if status.failed || !frame.complete || frame.consumed != 2 { #panic("frame success metadata") }
  state := ws.message_state(false)
  message: [32]u8
  control: [125]u8
  event := ws.receive(&status, &state, message[..], control[..], frame)
  if status.failed || event.detail != ws.WebSocketEventKind.Ready { #panic("event classification") }
  incomplete: fail.Status
  _ = ws.receive(&incomplete, &state, message[..], control[..], partial)
  if incomplete.failure.kind != fail.Kind.InvalidInput { #panic("event metadata") }

  upgrade: fail.Status
  _ = ws.validate_upgrade_request(&upgrade, "GET / HTTP/1.1\r\nBad Header: x\r\n\r\n")
  malformed_at(&upgrade, 19)
  fields: fail.Status
  _ = ws.validate_upgrade_request(&fields, "GET / HTTP/1.1\r\n\r\n")
  if fields.failure.kind != fail.Kind.InvalidInput { #panic("upgrade fields") }
  response: fail.Status
  ws.validate_upgrade_response(&response, "HTTP/1.1 2xx Bad\r\n\r\n", "")
  malformed_at(&response, 10)
  refused: fail.Status
  ws.validate_upgrade_response(&refused, "HTTP/1.1 200 OK\r\n\r\n", "")
  if refused.failure.kind != fail.Kind.InvalidInput { #panic("upgrade metadata") }
  ws.validate_upgrade_response(&status, "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n", "dGhlIHNhbXBsZSBub25jZQ==")
  if status.failed { #panic("upgrade success metadata") }

  routes: [1]http.TypedRoute<Trace>
  route_state := Trace{}
  router := http.typed_routes(routes[..], &route_state)
  invalid: fail.Status
  http.add(&invalid, &router, "GET", "/", nil)
  if invalid.failure.kind != fail.Kind.InvalidInput || router.count != 0 { #panic("invalid route result") }
  http.add(&status, &router, "GET", "/", typed_handler)
  if status.failed || router.count != 1 { #panic("route success result") }
  full: fail.Status
  http.add(&full, &router, "GET", "/other", typed_handler)
  if full.failure.kind != fail.Kind.Capacity || router.count != 1 { #panic("route capacity result") }

  for native in [0, -73] {
    trace := Trace{ native: #cast(isize, native) }
    reader := io.Reader{ data: &trace, read: read }
    writer := io.Writer{ data: &trace, write: write }
    storage: [128]u8
    server := http.server(reader, writer, storage[..])
    first: fail.Status
    _ = http.receive(&first, &server)
    denied_with(&first, &trace)
    again: fail.Status
    _ = http.receive(&again, &server)
    finished(&again)
    if trace.calls != 1 { #panic("HTTP native replay") }
    trace.calls = 0
    frames: [32]u8
    socket := ws.connection(reader, writer, frames[..], message[..], control[..], true)
    received: fail.Status
    _ = ws.connection_receive(&received, &socket)
    denied_with(&received, &trace)
    if trace.calls != 1 { #panic("WS native read metadata") }
    replay: fail.Status
    ws.connection_ping(&replay, &socket, "", 0)
    finished(&replay)
    if trace.calls != 1 { #panic("WS native read replay") }
    socket = ws.connection(reader, writer, frames[..], message[..], control[..], true)
    sent: fail.Status
    ws.connection_send(&sent, &socket, 1, "x", true, 1)
    denied_with(&sent, &trace)
    if trace.calls != 2 { #panic("WS native write metadata") }
    closing: fail.Status
    ws.connection_close(&closing, &socket, "", 0)
    finished(&closing)
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
