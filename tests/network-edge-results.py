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

SOURCE = r'''use "std/net/http" http
use "std/net/websocket" ws
use "std/io" io
use "std/io" errors
use "std/parse" parse
fn metadata(kind: parse.Kind, offset: usize, expected: parse.Kind, at: usize) {
  if kind != expected || offset != at { #panic("parser metadata golden") }
}
fn head(result: http.HttpHead, offset: usize) {
  metadata(result.failure.kind, result.offset, parse.Kind.Syntax, offset)
}
fn handler(response: *http.Response, request: *const http.Request) http.Result {
  return http.Result{}
}
struct Trace { calls: usize, native: isize }
fn read(raw: rawptr, dest: []u8) io.Transfer {
  trace := #cast(*Trace, raw)
  trace.calls += 1
  return io.Transfer{ kind: errors.Kind.PermissionDenied, error: trace.native, status: io.Status.Error }
}
fn write(raw: rawptr, source: []const u8) io.Transfer {
  trace := #cast(*Trace, raw)
  trace.calls += 1
  return io.Transfer{ kind: errors.Kind.PermissionDenied, error: trace.native, status: io.Status.Error }
}
fn main() {
  head(http.parse_request("GET / HTTP/1.1\r\nBad Header: x\r\n\r\n"), 19)
  head(http.parse_request("GET / HTTP/1.1\r\nContent-Length: 1x\r\n\r\n"), 33)
  head(http.parse_request("GET / HTTP/2.0\r\n\r\n"), 11)
  // Chunk framing headers exercise public parsers, without coupling to chunk producers.
  head(http.parse_request("GET / HTTP/1.1\r\nTransfer-Encoding: chunks\r\n\r\n"), 35)
  head(http.parse_response("HTTP/1.1 200 OK\r\nTransfer-Encoding: gzip\r\n\r\n"), 36)
  head(http.parse_response("HTTP/1.1 2xx Bad\r\n\r\n"), 10)
  head(http.parse_response("HTTP/1.1 200 OK\r\nBad Header: x\r\n\r\n"), 20)
  url := http.parse_url("http://host:8x/path")
  metadata(url.failure.kind, url.offset, parse.Kind.Syntax, 13)
  url = http.parse_url("http://user@host/path")
  metadata(url.failure.kind, url.offset, parse.Kind.Syntax, 11)
  url = http.parse_url("http://host:0/path")
  metadata(url.failure.kind, url.offset, parse.Kind.Syntax, 12)
  valid_head := http.parse_request("GET / HTTP/1.1\r\n\r\n")
  if valid_head.failure.kind != parse.Kind.Ok || valid_head.offset != 0 { #panic("request success metadata") }
  valid_head = http.parse_response("HTTP/1.1 200 OK\r\n\r\n")
  if valid_head.failure.kind != parse.Kind.Ok || valid_head.offset != 0 { #panic("response success metadata") }
  url = http.parse_url("http://host/path")
  if url.failure.kind != parse.Kind.Ok || url.offset != 0 { #panic("URL success metadata") }

  malformed: [4]u8 = [129, 126, 0, 1]
  frame := ws.parse_frame(malformed[..])
  metadata(frame.failure.kind, frame.offset, parse.Kind.Syntax, 2)
  for size in 0..4 {
    frame = ws.parse_frame(malformed[..size])
    metadata(frame.failure.kind, frame.offset, parse.Kind.Truncated, size)
  }
  reserved: [2]u8 = [193, 0]
  frame = ws.parse_frame(reserved[..])
  metadata(frame.failure.kind, frame.offset, parse.Kind.Syntax, 0)
  masked: [3]u8 = [129, 128, 0]
  frame = ws.parse_frame(masked[..])
  metadata(frame.failure.kind, frame.offset, parse.Kind.Truncated, 3)
  valid: [2]u8 = [129, 0]
  frame = ws.parse_frame(valid[..])
  if frame.failure.kind != parse.Kind.Ok || frame.offset != 0 || frame.consumed != 2 { #panic("frame success metadata") }
  state := ws.message_state(false)
  message: [32]u8
  control: [125]u8
  event := ws.receive(&state, message[..], control[..], frame)
  if event.failure.kind != errors.Kind.Ok || event.detail != ws.WebSocketEventKind.Ready { #panic("event classification") }
  event = ws.receive(&state, message[..], control[..], ws.parse_frame(malformed[..]))
  if event.failure.kind != errors.Kind.InvalidInput || event.offset != 2 { #panic("event metadata") }
  if event.detail != ws.WebSocketEventKind.Error { #panic("error event classification") }

  upgrade := ws.validate_upgrade_request("GET / HTTP/1.1\r\nBad Header: x\r\n\r\n")
  metadata(upgrade.failure.kind, upgrade.offset, parse.Kind.Syntax, 19)
  upgrade = ws.validate_upgrade_request("GET / HTTP/1.1\r\n\r\n")
  metadata(upgrade.failure.kind, upgrade.offset, parse.Kind.Syntax, 0)
  response := ws.validate_upgrade_response("HTTP/1.1 2xx Bad\r\n\r\n", "")
  if response.failure.kind != errors.Kind.InvalidInput || response.offset != 10 { #panic("upgrade metadata") }
  response = ws.validate_upgrade_response("HTTP/1.1 200 OK\r\n\r\n", "")
  if response.failure.kind != errors.Kind.InvalidInput || response.offset != 0 { #panic("upgrade metadata") }
  response = ws.validate_upgrade_response("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n", "dGhlIHNhbXBsZSBub25jZQ==")
  if response.failure.kind != io.Kind.Ok || response.failure.kind != errors.Kind.Ok || response.failure.native != 0 || response.offset != 0 { #panic("upgrade success metadata") }

  // Zero values are failures despite a zero native code; close preserves OS codes.
  zero := http.Result{}
  if zero.failure.kind != errors.Kind.Ok || zero.failure.native != 0 || zero.offset != 0 || zero.detail != http.ErrorKind.None { #panic("zero HTTP result") }
  ws_zero := ws.Result{}
  if ws_zero.failure.kind != errors.Kind.Ok || ws_zero.failure.native != 0 || ws_zero.offset != 0 { #panic("zero WS result") }
  connection := http.Connection{}
  http.close(&connection)
  routes: [1]http.Route
  router := http.router(routes[..], nil)
  route := http.route(&router, "GET", "/", nil)
  if route.failure.kind != errors.Kind.InvalidInput || route.offset != 0 { #panic("metadata") }
  if route.detail != http.ErrorKind.Invalid || router.count != 0 { #panic("invalid route result") }
  route = http.route(&router, "GET", "/", handler)
  if route.failure.kind != io.Kind.Ok || route.failure.kind != errors.Kind.Ok || route.failure.native != 0 || route.offset != 0 || router.count != 1 { #panic("route success result") }
  route = http.route(&router, "GET", "/other", handler)
  if route.failure.kind != errors.Kind.Capacity || route.offset != 0 { #panic("metadata") }
  if route.detail != http.ErrorKind.Capacity || router.count != 1 { #panic("route capacity result") }

  for native in [0, -73] {
    trace := Trace{ native: #cast(isize, native) }
    reader := io.Reader{ data: &trace, read: read }
    writer := io.Writer{ data: &trace, write: write }
    storage: [128]u8
    server := http.server(reader, writer, storage[..])
    first := http.receive(&server)
    again := http.receive(&server)
    if first.failure.kind == io.Kind.Ok || first.failure.kind != errors.Kind.PermissionDenied || first.failure.native != trace.native || first.offset != 0 || first.detail != http.ErrorKind.Io { #panic("HTTP native metadata") }
    if again.failure.kind == io.Kind.Ok || again.failure.kind != first.failure.kind || again.failure.native != first.failure.native || again.offset != first.offset || again.detail != first.detail || trace.calls != 1 { #panic("HTTP native replay") }
    trace.calls = 0
    frames: [32]u8
    socket := ws.connection(reader, writer, frames[..], message[..], control[..], true)
    received := ws.connection_receive(&socket)
    if received.failure.kind == io.Kind.Ok || received.failure.kind != errors.Kind.PermissionDenied || received.failure.native != trace.native || received.offset != 0 || trace.calls != 1 { #panic("WS native read metadata") }
    replay := ws.connection_ping(&socket, "", 0)
    if replay.failure.kind == io.Kind.Ok || replay.failure.kind != received.failure.kind || replay.failure.native != received.failure.native || replay.offset != received.offset || trace.calls != 1 { #panic("WS native read replay") }
    socket = ws.connection(reader, writer, frames[..], message[..], control[..], true)
    sent := ws.connection_send(&socket, 1, "x", true, 1)
    if sent.failure.kind == io.Kind.Ok || sent.failure.kind != errors.Kind.PermissionDenied || sent.failure.native != trace.native || sent.offset != 0 || trace.calls != 2 { #panic("WS native write metadata") }
    replay = ws.connection_close(&socket, "", 0)
    if replay.failure.kind == io.Kind.Ok || replay.failure.kind != sent.failure.kind || replay.failure.native != sent.failure.native || replay.offset != sent.offset || trace.calls != 2 { #panic("WS native write replay") }
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
print('PASS public network parser goldens, result metadata and native zero/nonzero (debug/release)')
