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
use "std/io" io
use "std/errors" errors
struct Trace { reads: usize, writes: usize, mode: usize, bytes: usize }
fn read(data: rawptr, destination: []u8) io.Result {
  trace := #cast(*Trace, data)
  trace.reads += 1
  if trace.mode == 0 { return io.Result{ error: -71, kind: errors.Kind.System, status: io.Status.Error } }
  if trace.mode == 1 { return io.Result{ status: io.Status.End } }
  if trace.mode == 2 { return io.Result{ transferred: #len(destination) + 1 } }
  if trace.mode == 3 { return io.Result{ error: 0, kind: errors.Kind.System, status: io.Status.Error } }
  if trace.mode == 8 {
    // A valid length prefix whose payload exceeds the frame buffer.
    for i in 0..#len(destination) { destination[i] = 0 }
    destination[0] = 130
    destination[1] = 126
    destination[3] = 126
    return io.Result{ transferred: #len(destination) }
  }
  if trace.mode == 9 {
    destination[0] = 129
    destination[1] = 126
    destination[2] = 0
    destination[3] = 1
    return io.Result{ transferred: 4 }
  }
  destination[0] = 136
  destination[1] = 0
  if trace.mode == 4 { destination[0] = 129 destination[1] = 128 }
  if trace.mode == 5 { return io.Result{ transferred: 2, error: -72, status: io.Status.Error } }
  if trace.mode == 6 { destination[0] = 0 destination[1] = 0 }
  if trace.mode == 7 { return io.Result{} }
  return io.Result{ transferred: 2 }
}
fn write(data: rawptr, source: []const u8) io.Result {
  trace := #cast(*Trace, data)
  trace.writes += 1
  if trace.mode == 10 { return io.Result{ error: -73, status: io.Status.Error } }
  if trace.mode == 11 { return io.Result{} }
  if trace.mode == 12 { return io.Result{ transferred: #len(source) + 1 } }
  if trace.mode == 13 { return io.Result{ error: 0, kind: errors.Kind.System, status: io.Status.Error } }
  if trace.mode == 14 {
    if trace.writes == 1 { trace.bytes += 1 return io.Result{ transferred: 1 } }
    return io.Result{ error: -74, status: io.Status.Error }
  }
  trace.bytes += #len(source)
  return io.Result{ transferred: #len(source) }
}
fn failure(result: ws.Result, kind: errors.Kind, native: isize, offset: usize) {
  if result.ok || result.kind != kind || result.error != native || result.offset != offset { #panic("structured failure metadata") }
}
fn success(result: ws.Result) bool {
  return result.ok && result.kind == errors.Kind.None && result.error == 0 && result.offset == 0
}
fn sticky(connection: *ws.WebSocketConnection, trace: *Trace, kind: errors.Kind, expected: isize, offset: usize) {
  reads := trace.reads
  writes := trace.writes
  bytes := trace.bytes
  trace.mode = 99
  for i in 0..3 {
    failure(ws.connection_send(connection, 1, "later", true, 0), kind, expected, offset)
    failure(ws.connection_ping(connection, "", 0), kind, expected, offset)
    failure(ws.connection_pong(connection, "", 0), kind, expected, offset)
    failure(ws.connection_close(connection, "", 0), kind, expected, offset)
    result := ws.connection_receive(connection)
    if result.ok || result.error != expected || result.kind != kind || result.offset != offset || result.event.ok { #panic("receive lost first error") }
  }
  if trace.reads != reads || trace.writes != writes || trace.bytes != bytes { #panic("I/O after failure") }
}
struct Wire { data: []const u8, at: usize, step: usize, calls: usize }
fn wire_read(raw: rawptr, destination: []u8) io.Result {
  wire := #cast(*Wire, raw)
  wire.calls += 1
  count := #len(wire.data) - wire.at
  if count > wire.step { count = wire.step }
  if count > #len(destination) { count = #len(destination) }
  for i in 0..count { destination[i] = wire.data[wire.at + i] }
  wire.at += count
  if count == 0 { return io.Result{status: io.Status.End} }
  return io.Result{transferred: count}
}
fn coalesced() {
  isolated := Wire{data: "\x81\x01a", step: 32}
  single_sent := Trace{mode: 99}
  available: [32]u8 = [] single_message: [32]u8 = [] controls: [125]u8 = []
  reusable := ws.connection(io.Reader{data: &isolated, read: &wire_read}, io.Writer{data: &single_sent, write: &write}, available[..], single_message[..], controls[..], true)
  if !ws.connection_receive(&reusable).ok { #panic("single frame") }
  if !ws.connection_send(&reusable, 1, "abcdefghijklmnopqrstuvwxyz", true, 1).ok || single_sent.bytes != 32 { #panic("fully consumed capacity") }
  for step in [1, 2, 3, 4, 32] {
    wire := Wire{data: "\x81\x01a\x81\x01b\x88\x00", step: #cast(usize, step)}
    frames: [32]u8 = [] message: [32]u8 = [] control: [125]u8 = []
    sent := Trace{mode: 99}
    state := ws.connection(io.Reader{data: &wire, read: &wire_read}, io.Writer{data: &sent, write: &write}, frames[..], message[..], control[..], true)
    a := ws.connection_receive(&state)
    if !a.ok || a.event.detail != ws.WebSocketEventKind.Ready || #len(a.event.payload) != 1 || a.event.payload[0] != 'a' { #panic("coalesced first") }
    if !ws.connection_pong(&state, "p", 1).ok || sent.writes != 1 || a.event.payload[0] != 'a' { #panic("send with pending frames") }
    b := ws.connection_receive(&state)
    if !b.ok || b.event.detail != ws.WebSocketEventKind.Ready || #len(b.event.payload) != 1 || b.event.payload[0] != 'b' { #panic("coalesced second") }
    closed := ws.connection_receive(&state)
    if !closed.ok || closed.event.detail != ws.WebSocketEventKind.Close { #panic("coalesced close") }
    if step == 32 && wire.calls != 1 { #panic("coalesced extra read") }
    wire = Wire{data: "\x01\x01a\x89\x01p\x80\x01b", step: #cast(usize, step)}
    state = ws.connection(io.Reader{data: &wire, read: &wire_read}, io.Writer{data: &sent, write: &write}, frames[..], message[..], control[..], true)
    ping := ws.connection_receive(&state)
    if !ping.ok || ping.event.detail != ws.WebSocketEventKind.Ping || #len(ping.event.payload) != 1 || ping.event.payload[0] != 'p' { #panic("fragmented ping") }
    if !ws.connection_pong(&state, ping.event.payload, 1).ok || sent.writes != 2 || ping.event.payload[0] != 'p' { #panic("send with pending continuation") }
    ab := ws.connection_receive(&state)
    if !ab.ok || ab.event.detail != ws.WebSocketEventKind.Ready || #len(ab.event.payload) != 2 || ab.event.payload[0] != 'a' || ab.event.payload[1] != 'b' { #panic("fragmented remainder") }
    if step == 32 && wire.calls != 1 { #panic("fragmented extra read") }
  }
}
fn main() {
  coalesced()
  trace := Trace{}
  frames: [32]u8 = []
  message: [32]u8 = []
  control: [125]u8 = []
  reader := io.Reader{ data: &trace, read: &read }
  writer := io.Writer{ data: &trace, write: &write }
  zero := ws.WebSocketConnection{}
  if !success(ws.connection_close(&zero, "", 0)) || zero.failed { #panic("zero close") }
  failure(ws.connection_send(&zero, 1, "", true, 0), errors.Kind.InvalidState, 0, 0)
  sticky(&zero, &trace, errors.Kind.InvalidState, 0, 0)
  zero = ws.WebSocketConnection{}
  initial := ws.connection_receive(&zero)
  if initial.ok || initial.kind != errors.Kind.InvalidState || initial.error != 0 || initial.offset != 0 { #panic("zero receive") }
  sticky(&zero, &trace, errors.Kind.InvalidState, 0, 0)
  for mode in 0..10 {
    trace = Trace{ mode: mode }
    connection := ws.connection(reader, writer, frames[..], message[..], control[..], true)
    result := ws.connection_receive(&connection)
    expected: isize = -71
    if mode == 1 || mode == 7 { expected = 0 }
    if mode == 2 { expected = -5 }
    if mode == 3 { expected = 0 }
    if mode == 4 || mode == 6 || mode == 9 { expected = 0 }
    if mode == 5 { expected = -72 }
    if mode == 8 { expected = 0 }
    kind := errors.Kind.System
    if mode == 1 || mode == 7 { kind = errors.Kind.InvalidState }
    if mode == 4 || mode == 6 || mode == 9 { kind = errors.Kind.InvalidInput }
    if mode == 8 { kind = errors.Kind.Capacity }
    offset: usize = 0
    if mode == 9 { offset = 2 }
    if result.ok || result.error != expected || result.kind != kind || result.offset != offset || trace.reads == 0 { #panic("initial receive failure") }
    sticky(&connection, &trace, kind, expected, offset)
  }
  for mode in 10..15 {
    trace = Trace{ mode: mode }
    connection := ws.connection(reader, writer, frames[..], message[..], control[..], true)
    expected: isize = -73
    if mode == 11 || mode == 12 { expected = -5 }
    if mode == 13 { expected = 0 }
    if mode == 14 { expected = -74 }
    failure(ws.connection_send(&connection, 1, "hello", true, 1), errors.Kind.System, expected, 0)
    if trace.writes == 0 { #panic("writer not invoked") }
    if mode == 14 && (trace.writes != 2 || trace.bytes != 1) { #panic("partial write trace") }
    sticky(&connection, &trace, errors.Kind.System, expected, 0)
  }
  trace = Trace{ mode: 99 }
  connection := ws.connection(reader, writer, frames[..0], message[..], control[..], true)
  failure(ws.connection_send(&connection, 1, "", true, 0), errors.Kind.Capacity, 0, 0)
  sticky(&connection, &trace, errors.Kind.Capacity, 0, 0)
  connection = ws.connection(reader, writer, frames[..], message[..], control[..], true)
  failure(ws.connection_send(&connection, 3, "", true, 0), errors.Kind.InvalidInput, 0, 0)
  sticky(&connection, &trace, errors.Kind.InvalidInput, 0, 0)
  connection = ws.connection(reader, writer, frames[..0], message[..], control[..], true)
  capacity_result := ws.connection_receive(&connection)
  if capacity_result.ok || capacity_result.kind != errors.Kind.Capacity || capacity_result.error != 0 || capacity_result.offset != 0 { #panic("receive capacity") }
  sticky(&connection, &trace, errors.Kind.Capacity, 0, 0)
  connection = ws.connection(io.Reader{}, writer, frames[..], message[..], control[..], true)
  nil_reader_result := ws.connection_receive(&connection)
  if nil_reader_result.ok || nil_reader_result.kind != errors.Kind.InvalidState || nil_reader_result.error != 0 || nil_reader_result.offset != 0 { #panic("nil reader") }
  sticky(&connection, &trace, errors.Kind.InvalidState, 0, 0)
  connection = ws.connection(reader, io.Writer{}, frames[..], message[..], control[..], true)
  failure(ws.connection_send(&connection, 1, "", true, 0), errors.Kind.InvalidState, 0, 0)
  sticky(&connection, &trace, errors.Kind.InvalidState, 0, 0)
  // Constructor assignment resets failure; a normal peer Close allows one reply.
  connection = ws.connection(reader, writer, frames[..], message[..], control[..], true)
  result := ws.connection_receive(&connection)
  if !result.ok || result.event.detail != ws.WebSocketEventKind.Close || !result.event.ok || result.event.kind != errors.Kind.None || result.event.error != 0 || result.kind != errors.Kind.None || result.error != 0 || connection.failed { #panic("normal close") }
  reads := trace.reads
  if !ws.connection_receive(&connection).ok || trace.reads != reads { #panic("repeat peer close") }
  failure(ws.connection_ping(&connection, "", 0), errors.Kind.InvalidState, 0, 0)
  if connection.failed { #panic("closed ping") }
  if !success(ws.connection_close(&connection, "", 0)) { #panic("close reply") }
  writes := trace.writes
  if !success(ws.connection_close(&connection, "", 0)) || trace.writes != writes { #panic("repeat close") }
  failure(ws.connection_send(&connection, 1, "", true, 0), errors.Kind.InvalidState, 0, 0)
  if connection.failed { #panic("closed send") }
  connection = ws.connection(reader, writer, frames[..], message[..], control[..], true)
  if !success(ws.connection_close(&connection, "", 0)) || !ws.connection_receive(&connection).ok { #panic("local close handshake") }
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
print('PASS WebSocket sticky failures, independent callback traces, zero/reset and normal close (debug/release)')
