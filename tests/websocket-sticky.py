#!/usr/bin/env python3
"""Bounded callback traces for WebSocket connection failures and normal close."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
if sys.platform not in ('linux', 'darwin', 'win32'):
    print('SKIP WebSocket callback runtime: unsupported native host')
    raise SystemExit(0)

SOURCE = r'''use "std/net/websocket" ws
use "std/fail"
use "std/io" io
struct Trace { reads: usize, writes: usize, mode: usize, bytes: usize }
fn trace_failure(status: *fail.Status, native: isize) usize {
  failure := fail.make(fail.Kind.System, "trace", "", "")
  failure.native = native
  fail.set(status, failure)
  return 0
}
fn read(data: rawptr, status: *fail.Status, destination: []u8) usize {
  trace := #cast(*Trace, data)
  trace.reads += 1
  if trace.mode == 0 { return trace_failure(status, -71) }
  if trace.mode == 1 || trace.mode == 7 { return 0 }
  if trace.mode == 2 { return #len(destination) + 1 }
  if trace.mode == 3 { return trace_failure(status, 0) }
  if trace.mode == 8 {
    // A valid length prefix whose payload exceeds the frame buffer.
    for i in 0..#len(destination) { destination[i] = 0 }
    destination[0] = 130
    destination[1] = 126
    destination[3] = 126
    return #len(destination)
  }
  if trace.mode == 9 {
    destination[0] = 129
    destination[1] = 126
    destination[2] = 0
    destination[3] = 1
    return 4
  }
  destination[0] = 136
  destination[1] = 0
  if trace.mode == 4 {
    destination[0] = 129
    destination[1] = 128
  }
  if trace.mode == 5 {
    _ = trace_failure(status, -72)
    return 2
  }
  if trace.mode == 6 {
    destination[0] = 0
    destination[1] = 0
  }
  return 2
}
fn write(data: rawptr, status: *fail.Status, source: []const u8) usize {
  trace := #cast(*Trace, data)
  trace.writes += 1
  if trace.mode == 10 { return trace_failure(status, -73) }
  if trace.mode == 11 { return 0 }
  if trace.mode == 12 { return #len(source) + 1 }
  if trace.mode == 13 { return trace_failure(status, 0) }
  if trace.mode == 14 {
    if trace.writes == 1 {
      trace.bytes += 1
      return 1
    }
    return trace_failure(status, -74)
  }
  trace.bytes += #len(source)
  return #len(source)
}
fn failed_with(status: *const fail.Status, kind: fail.Kind, native: isize, offset: usize) {
  if !status.failed || status.failure.kind != kind || status.failure.native != native || status.failure.offset != offset { #panic("structured failure metadata") }
}
// After a failure every call fails with InvalidState and does no I/O.
fn stays_failed(connection: *ws.WebSocketConnection, trace: *Trace) {
  reads := trace.reads
  writes := trace.writes
  bytes := trace.bytes
  trace.mode = 99
  for i in 0..3 {
    send: fail.Status
    ws.connection_send(&send, connection, 1, "later", true, 0)
    failed_with(&send, fail.Kind.InvalidState, 0, 0)
    ping: fail.Status
    ws.connection_ping(&ping, connection, "", 0)
    failed_with(&ping, fail.Kind.InvalidState, 0, 0)
    pong: fail.Status
    ws.connection_pong(&pong, connection, "", 0)
    failed_with(&pong, fail.Kind.InvalidState, 0, 0)
    closing: fail.Status
    ws.connection_close(&closing, connection, "", 0)
    failed_with(&closing, fail.Kind.InvalidState, 0, 0)
    receive: fail.Status
    _ = ws.connection_receive(&receive, connection)
    failed_with(&receive, fail.Kind.InvalidState, 0, 0)
  }
  if trace.reads != reads || trace.writes != writes || trace.bytes != bytes { #panic("I/O after failure") }
}
struct Wire { data: []const u8, at: usize, step: usize, calls: usize }
fn wire_read(raw: rawptr, status: *fail.Status, destination: []u8) usize {
  wire := #cast(*Wire, raw)
  wire.calls += 1
  count := #len(wire.data) - wire.at
  if count > wire.step { count = wire.step }
  if count > #len(destination) { count = #len(destination) }
  for i in 0..count { destination[i] = wire.data[wire.at + i] }
  wire.at += count
  return count
}
fn coalesced() {
  status := fail.Status{ on_failure: fail.panic_on_failure }
  isolated := Wire{data: "\x81\x01a", step: 32}
  single_sent := Trace{mode: 99}
  available: [32]u8
  single_message: [32]u8
  controls: [125]u8
  reusable := ws.connection(io.Reader{ data: &isolated, read: wire_read }, io.Writer{ data: &single_sent, write: write }, available[..], single_message[..], controls[..], true)
  _ = ws.connection_receive(&status, &reusable)
  ws.connection_send(&status, &reusable, 1, "abcdefghijklmnopqrstuvwxyz", true, 1)
  if single_sent.bytes != 32 { #panic("fully consumed capacity") }
  for step in [1, 2, 3, 4, 32] {
    wire := Wire{data: "\x81\x01a\x81\x01b\x88\x00", step: #cast(usize, step)}
    frames: [32]u8
    message: [32]u8
    control: [125]u8
    sent := Trace{mode: 99}
    state := ws.connection(io.Reader{ data: &wire, read: wire_read }, io.Writer{ data: &sent, write: write }, frames[..], message[..], control[..], true)
    a := ws.connection_receive(&status, &state)
    if a.detail != ws.WebSocketEventKind.Ready || #len(a.payload) != 1 || a.payload[0] != 'a' { #panic("coalesced first") }
    ws.connection_pong(&status, &state, "p", 1)
    if sent.writes != 1 || a.payload[0] != 'a' { #panic("send with pending frames") }
    b := ws.connection_receive(&status, &state)
    if b.detail != ws.WebSocketEventKind.Ready || #len(b.payload) != 1 || b.payload[0] != 'b' { #panic("coalesced second") }
    closed := ws.connection_receive(&status, &state)
    if closed.detail != ws.WebSocketEventKind.Close { #panic("coalesced close") }
    if step == 32 && wire.calls != 1 { #panic("coalesced extra read") }
    wire = Wire{data: "\x01\x01a\x89\x01p\x80\x01b", step: #cast(usize, step)}
    state = ws.connection(io.Reader{ data: &wire, read: wire_read }, io.Writer{ data: &sent, write: write }, frames[..], message[..], control[..], true)
    ping := ws.connection_receive(&status, &state)
    if ping.detail != ws.WebSocketEventKind.Ping || #len(ping.payload) != 1 || ping.payload[0] != 'p' { #panic("fragmented ping") }
    ws.connection_pong(&status, &state, ping.payload, 1)
    if sent.writes != 2 || ping.payload[0] != 'p' { #panic("send with pending continuation") }
    ab := ws.connection_receive(&status, &state)
    if ab.detail != ws.WebSocketEventKind.Ready || #len(ab.payload) != 2 || ab.payload[0] != 'a' || ab.payload[1] != 'b' { #panic("fragmented remainder") }
    if step == 32 && wire.calls != 1 { #panic("fragmented extra read") }
  }
}
fn main() {
  coalesced()
  trace := Trace{}
  frames: [32]u8
  message: [32]u8
  control: [125]u8
  reader := io.Reader{ data: &trace, read: read }
  writer := io.Writer{ data: &trace, write: write }
  zero := ws.WebSocketConnection{}
  quiet: fail.Status
  ws.connection_close(&quiet, &zero, "", 0)
  if quiet.failed || zero.failed { #panic("zero close") }
  inactive: fail.Status
  ws.connection_send(&inactive, &zero, 1, "", true, 0)
  failed_with(&inactive, fail.Kind.InvalidState, 0, 0)
  stays_failed(&zero, &trace)
  zero = ws.WebSocketConnection{}
  initial: fail.Status
  _ = ws.connection_receive(&initial, &zero)
  failed_with(&initial, fail.Kind.InvalidState, 0, 0)
  stays_failed(&zero, &trace)
  for mode in 0..10 {
    trace = Trace{ mode: mode }
    connection := ws.connection(reader, writer, frames[..], message[..], control[..], true)
    result: fail.Status
    _ = ws.connection_receive(&result, &connection)
    expected: isize = -71
    if mode == 1 || mode == 7 || mode == 3 || mode == 4 || mode == 6 || mode == 8 || mode == 9 { expected = 0 }
    if mode == 2 { expected = -5 }
    if mode == 5 { expected = -72 }
    kind := fail.Kind.System
    // A stream that ends inside a frame, or a protocol violation.
    if mode == 1 || mode == 7 || mode == 4 || mode == 6 || mode == 9 { kind = fail.Kind.InvalidInput }
    if mode == 8 { kind = fail.Kind.Capacity }
    offset: usize = 0
    if mode == 9 { offset = 2 }
    failed_with(&result, kind, expected, offset)
    if trace.reads == 0 { #panic("reader not invoked") }
    stays_failed(&connection, &trace)
  }
  for mode in 10..15 {
    trace = Trace{ mode: mode }
    connection := ws.connection(reader, writer, frames[..], message[..], control[..], true)
    expected: isize = -73
    if mode == 11 || mode == 12 { expected = -5 }
    if mode == 13 { expected = 0 }
    if mode == 14 { expected = -74 }
    sent: fail.Status
    ws.connection_send(&sent, &connection, 1, "hello", true, 1)
    failed_with(&sent, fail.Kind.System, expected, 0)
    if trace.writes == 0 { #panic("writer not invoked") }
    if mode == 14 && (trace.writes != 2 || trace.bytes != 1) { #panic("partial write trace") }
    stays_failed(&connection, &trace)
  }
  trace = Trace{ mode: 99 }
  connection := ws.connection(reader, writer, frames[..0], message[..], control[..], true)
  small: fail.Status
  ws.connection_send(&small, &connection, 1, "", true, 0)
  failed_with(&small, fail.Kind.Capacity, 0, 0)
  stays_failed(&connection, &trace)
  connection = ws.connection(reader, writer, frames[..], message[..], control[..], true)
  opcode: fail.Status
  ws.connection_send(&opcode, &connection, 3, "", true, 0)
  failed_with(&opcode, fail.Kind.InvalidInput, 0, 0)
  stays_failed(&connection, &trace)
  connection = ws.connection(reader, writer, frames[..0], message[..], control[..], true)
  capacity: fail.Status
  _ = ws.connection_receive(&capacity, &connection)
  failed_with(&capacity, fail.Kind.Capacity, 0, 0)
  stays_failed(&connection, &trace)
  connection = ws.connection(io.Reader{}, writer, frames[..], message[..], control[..], true)
  no_reader: fail.Status
  _ = ws.connection_receive(&no_reader, &connection)
  failed_with(&no_reader, fail.Kind.InvalidState, 0, 0)
  stays_failed(&connection, &trace)
  connection = ws.connection(reader, io.Writer{}, frames[..], message[..], control[..], true)
  no_writer: fail.Status
  ws.connection_send(&no_writer, &connection, 1, "", true, 0)
  failed_with(&no_writer, fail.Kind.InvalidState, 0, 0)
  stays_failed(&connection, &trace)
  // A fresh connection starts clean; a normal peer Close allows one reply.
  status: fail.Status
  connection = ws.connection(reader, writer, frames[..], message[..], control[..], true)
  result := ws.connection_receive(&status, &connection)
  if status.failed || result.detail != ws.WebSocketEventKind.Close || connection.failed { #panic("normal close") }
  reads := trace.reads
  _ = ws.connection_receive(&status, &connection)
  if status.failed || trace.reads != reads { #panic("repeat peer close") }
  closed_ping: fail.Status
  ws.connection_ping(&closed_ping, &connection, "", 0)
  failed_with(&closed_ping, fail.Kind.InvalidState, 0, 0)
  if connection.failed { #panic("closed ping") }
  ws.connection_close(&status, &connection, "", 0)
  if status.failed { #panic("close reply") }
  writes := trace.writes
  ws.connection_close(&status, &connection, "", 0)
  if status.failed || trace.writes != writes { #panic("repeat close") }
  closed_send: fail.Status
  ws.connection_send(&closed_send, &connection, 1, "", true, 0)
  failed_with(&closed_send, fail.Kind.InvalidState, 0, 0)
  if connection.failed { #panic("closed send") }
  connection = ws.connection(reader, writer, frames[..], message[..], control[..], true)
  ws.connection_close(&status, &connection, "", 0)
  _ = ws.connection_receive(&status, &connection)
  if status.failed { #panic("local close handshake") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-websocket-sticky-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    for mode in ('--debug', '--release'):
        output = project / ('program.exe' if os.name == 'nt' else 'program')
        subprocess.run([str(DYN), 'build', str(project), mode, '--no-cache', '--quiet',
                        '--output', str(output)], env=dict(os.environ, DYN_SDK=str(ROOT)), check=True, timeout=90)
        subprocess.run([str(output)], check=True, timeout=10)
print('PASS WebSocket failures stay failed with no further I/O, callback traces, zero/reset and normal close (debug/release)')
