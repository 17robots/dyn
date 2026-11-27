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

SOURCE = r'''use ws "std/net/websocket"
use "std/bytes"
use io "std/io"
struct Trace { reads: usize, writes: usize, mode: usize, bytes: usize }
fn read(data: rawptr, destination: []u8) usize!io.IoErr {
  trace := #cast(*Trace, data)
  trace.reads += 1
  if trace.mode == 0 { fail .System(-71) }
  if trace.mode == 1 || trace.mode == 7 { return 0 }
  if trace.mode == 2 { return destination.len + 1 }
  if trace.mode == 3 { fail .System(0) }
  if trace.mode == 5 { fail .System(-72) }
  if trace.mode == 8 {
    // A valid length prefix whose payload exceeds the frame buffer.
    for i in 0..destination.len { destination[i] = 0 }
    destination[0] = 130
    destination[1] = 126
    destination[3] = 126
    return destination.len
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
  if trace.mode == 6 {
    destination[0] = 0
    destination[1] = 0
  }
  return 2
}
fn write(data: rawptr, source: []const u8) usize!io.IoErr {
  trace := #cast(*Trace, data)
  trace.writes += 1
  if trace.mode == 10 { fail .System(-73) }
  if trace.mode == 11 { return 0 }
  if trace.mode == 12 { return source.len + 1 }
  if trace.mode == 13 { fail .System(0) }
  if trace.mode == 14 {
    if trace.writes == 1 {
      trace.bytes += 1
      return 1
    }
    fail .System(-74)
  }
  trace.bytes += source.len
  return source.len
}
// Whether a is b, System codes included.
fn same(a: io.IoErr, b: io.IoErr) bool {
  case a {
    .System(x) => {
      case b {
        .System(y) => { return x == y }
        _ => { return false }
      }
    }
    _ => {}
  }
  case b {
    .System(y) => { return false }
    _ => {}
  }
  return bytes.equal(io.text(a), io.text(b))
}
fn failed_with(err: io.IoErr, expected: io.IoErr) {
  if !same(err, expected) { #panic("structured failure") }
}
fn send_err(connection: *ws.WebSocketConnection, opcode: u8, payload: []const u8, mask: u32) io.IoErr {
  ws.connection_send(connection, opcode, payload, true, mask) catch err { return err }
  #panic("send unexpectedly succeeded")
}
fn ping_err(connection: *ws.WebSocketConnection) io.IoErr {
  ws.connection_ping(connection, "", 0) catch err { return err }
  #panic("ping unexpectedly succeeded")
}
fn pong_err(connection: *ws.WebSocketConnection) io.IoErr {
  ws.connection_pong(connection, "", 0) catch err { return err }
  #panic("pong unexpectedly succeeded")
}
fn close_err(connection: *ws.WebSocketConnection) io.IoErr {
  ws.connection_close(connection, "", 0) catch err { return err }
  #panic("close unexpectedly succeeded")
}
fn receive_err(connection: *ws.WebSocketConnection) io.IoErr {
  _ = ws.connection_receive(connection) catch err { return err }
  #panic("receive unexpectedly succeeded")
}
fn receive(connection: *ws.WebSocketConnection) ws.WebSocketEvent {
  return ws.connection_receive(connection) catch { #panic("receive") }
}
// After a failure every call fails with InvalidInput and does no I/O.
fn stays_failed(connection: *ws.WebSocketConnection, trace: *Trace) {
  reads := trace.reads
  writes := trace.writes
  sent := trace.bytes
  trace.mode = 99
  for i in 0..3 {
    failed_with(send_err(connection, 1, "later", 0), io.IoErr.InvalidInput)
    failed_with(ping_err(connection), io.IoErr.InvalidInput)
    failed_with(pong_err(connection), io.IoErr.InvalidInput)
    failed_with(close_err(connection), io.IoErr.InvalidInput)
    failed_with(receive_err(connection), io.IoErr.InvalidInput)
  }
  if trace.reads != reads || trace.writes != writes || trace.bytes != sent { #panic("I/O after failure") }
}
struct Wire { data: []const u8, at: usize, step: usize, calls: usize }
fn wire_read(raw: rawptr, destination: []u8) usize!io.IoErr {
  wire := #cast(*Wire, raw)
  wire.calls += 1
  count := wire.data.len - wire.at
  if count > wire.step { count = wire.step }
  if count > destination.len { count = destination.len }
  for i in 0..count { destination[i] = wire.data[wire.at + i] }
  wire.at += count
  return count
}
fn coalesced() {
  isolated := Wire{data: "\x81\x01a", step: 32}
  single_sent := Trace{mode: 99}
  available: [32]u8
  single_message: [32]u8
  controls: [125]u8
  reusable := ws.connection(io.Reader{ data: &isolated, read: wire_read }, io.Writer{ data: &single_sent, write: write }, available[..], single_message[..], controls[..], true)
  _ = receive(&reusable)
  ws.connection_send(&reusable, 1, "abcdefghijklmnopqrstuvwxyz", true, 1) catch { #panic("send") }
  if single_sent.bytes != 32 { #panic("fully consumed capacity") }
  for step in [1, 2, 3, 4, 32] {
    wire := Wire{data: "\x81\x01a\x81\x01b\x88\x00", step: #cast(usize, step)}
    frames: [32]u8
    message: [32]u8
    control: [125]u8
    sent := Trace{mode: 99}
    state := ws.connection(io.Reader{ data: &wire, read: wire_read }, io.Writer{ data: &sent, write: write }, frames[..], message[..], control[..], true)
    a := receive(&state)
    if a.detail != ws.WebSocketEventKind.Ready || a.payload.len != 1 || a.payload[0] != 'a' { #panic("coalesced first") }
    ws.connection_pong(&state, "p", 1) catch { #panic("pong") }
    if sent.writes != 1 || a.payload[0] != 'a' { #panic("send with pending frames") }
    b := receive(&state)
    if b.detail != ws.WebSocketEventKind.Ready || b.payload.len != 1 || b.payload[0] != 'b' { #panic("coalesced second") }
    closed := receive(&state)
    if closed.detail != ws.WebSocketEventKind.Close { #panic("coalesced close") }
    if step == 32 && wire.calls != 1 { #panic("coalesced extra read") }
    wire = Wire{data: "\x01\x01a\x89\x01p\x80\x01b", step: #cast(usize, step)}
    state = ws.connection(io.Reader{ data: &wire, read: wire_read }, io.Writer{ data: &sent, write: write }, frames[..], message[..], control[..], true)
    ping := receive(&state)
    if ping.detail != ws.WebSocketEventKind.Ping || ping.payload.len != 1 || ping.payload[0] != 'p' { #panic("fragmented ping") }
    ws.connection_pong(&state, ping.payload, 1) catch { #panic("pong") }
    if sent.writes != 2 || ping.payload[0] != 'p' { #panic("send with pending continuation") }
    ab := receive(&state)
    if ab.detail != ws.WebSocketEventKind.Ready || ab.payload.len != 2 || ab.payload[0] != 'a' || ab.payload[1] != 'b' { #panic("fragmented remainder") }
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
  ws.connection_close(&zero, "", 0) catch { #panic("zero close") }
  if zero.failed { #panic("zero close") }
  failed_with(send_err(&zero, 1, "", 0), io.IoErr.InvalidInput)
  stays_failed(&zero, &trace)
  zero = ws.WebSocketConnection{}
  failed_with(receive_err(&zero), io.IoErr.InvalidInput)
  stays_failed(&zero, &trace)
  for mode in 0..10 {
    trace = Trace{ mode: mode }
    connection := ws.connection(reader, writer, frames[..], message[..], control[..], true)
    // A stream that ends inside a frame, or a protocol violation.
    expected := io.IoErr.InvalidInput
    if mode == 0 { expected = io.IoErr.System(-71) }
    if mode == 2 { expected = io.IoErr.System(-5) }
    if mode == 3 { expected = io.IoErr.System(0) }
    if mode == 5 { expected = io.IoErr.System(-72) }
    if mode == 8 { expected = io.IoErr.Capacity }
    failed_with(receive_err(&connection), expected)
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
    failed_with(send_err(&connection, 1, "hello", 1), io.IoErr.System(expected))
    if trace.writes == 0 { #panic("writer not invoked") }
    if mode == 14 && (trace.writes != 2 || trace.bytes != 1) { #panic("partial write trace") }
    stays_failed(&connection, &trace)
  }
  trace = Trace{ mode: 99 }
  connection := ws.connection(reader, writer, frames[..0], message[..], control[..], true)
  failed_with(send_err(&connection, 1, "", 0), io.IoErr.Capacity)
  stays_failed(&connection, &trace)
  connection = ws.connection(reader, writer, frames[..], message[..], control[..], true)
  failed_with(send_err(&connection, 3, "", 0), io.IoErr.InvalidInput)
  stays_failed(&connection, &trace)
  connection = ws.connection(reader, writer, frames[..0], message[..], control[..], true)
  failed_with(receive_err(&connection), io.IoErr.Capacity)
  stays_failed(&connection, &trace)
  connection = ws.connection(io.Reader{}, writer, frames[..], message[..], control[..], true)
  failed_with(receive_err(&connection), io.IoErr.InvalidInput)
  stays_failed(&connection, &trace)
  connection = ws.connection(reader, io.Writer{}, frames[..], message[..], control[..], true)
  failed_with(send_err(&connection, 1, "", 0), io.IoErr.InvalidInput)
  stays_failed(&connection, &trace)
  // A fresh connection starts clean; a normal peer Close allows one reply.
  connection = ws.connection(reader, writer, frames[..], message[..], control[..], true)
  result := receive(&connection)
  if result.detail != ws.WebSocketEventKind.Close || connection.failed { #panic("normal close") }
  reads := trace.reads
  _ = receive(&connection)
  if trace.reads != reads { #panic("repeat peer close") }
  failed_with(ping_err(&connection), io.IoErr.InvalidInput)
  if connection.failed { #panic("closed ping") }
  ws.connection_close(&connection, "", 0) catch { #panic("close reply") }
  writes := trace.writes
  ws.connection_close(&connection, "", 0) catch { #panic("repeat close") }
  if trace.writes != writes { #panic("repeat close") }
  failed_with(send_err(&connection, 1, "", 0), io.IoErr.InvalidInput)
  if connection.failed { #panic("closed send") }
  connection = ws.connection(reader, writer, frames[..], message[..], control[..], true)
  ws.connection_close(&connection, "", 0) catch { #panic("local close") }
  _ = ws.connection_receive(&connection) catch { #panic("local close handshake") }
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
