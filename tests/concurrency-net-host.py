#!/usr/bin/env python3
"""Execute shared thread/TCP/UDP contracts natively; --cross only links targets."""
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build'/('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve())
SOURCE = r'''use "std/net"
use "std/thread"
use "std/fail"
use "std/mem" mem
use "std/sync"
use "std/bytes"
struct Context { listener: net.Listener, ready: sync.AtomicU32, count: sync.AtomicU64 }
fn worker(shared: *Context) isize {
  for sync.load_u32(&shared.ready) == 0 { thread.yield_now() }
  status := fail.Status{ on_failure: fail.panic_on_failure }
  connection := net.listener_accept(&status, &shared.listener)
  defer { net.connection_close(&connection) }
  buffer: [4]u8
  at: usize = 0
  for at < 4 {
    part := net.connection_read(&status, &connection, buffer[at..])
    if part == 0 { #panic("server read") }
    at += part
  }
  if !bytes.equal(buffer[..], "ping") { #panic("request") }
  _ = net.connection_write(&status, &connection, "pong")
  for i in 0..10000 { _ = sync.fetch_add_u64(&shared.count, 1) }
  return 0
}
fn main() {
  arena := mem.arena_alloc(0)
  defer { mem.arena_release(arena) }
  status := fail.Status{ on_failure: fail.panic_on_failure }
  idle := thread.Thread{}
  thread.join(&status, &idle)
  if thread.id(&idle) != 0 { #panic("empty join") }
  stack: [131072]u8
  mark:=mem.arena_mark(arena)
  short: fail.Status
  rejected:=thread.spawn(arena, &short, stack[..0], worker, nil)
  if short.failure.kind!=fail.Kind.InvalidInput || short.failure.native!=0 || rejected!=nil || mem.arena_mark(arena)!=mark { #panic("short stack") }
  address := net.ipv4(127, 0, 0, 1, 0)
  shared := Context{ listener: net.tcp_listen_ipv4(&status, &address, 4) }
  defer { net.listener_close(&shared.listener) }
  local := net.Address{}
  net.local_address(&status, shared.listener.descriptor, &local)
  if local.length != 16 { #panic("local address") }
  port := (#cast(u16, local.bytes[2]) << 8) | #cast(u16, local.bytes[3])
  if port == 0 { #panic("ephemeral port") }
  active:=thread.spawn(arena, &status, stack[..], worker, &shared)
  if active==nil || thread.id(active)==0 { #panic("active ownership") }
  sync.store_u32(&shared.ready, 1)
  address = net.ipv4(127, 0, 0, 1, port)
  connection := net.tcp_connect_ipv4(&status, &address)
  net.send_timeout(&status, connection.descriptor, 2000)
  net.receive_timeout(&status, connection.descriptor, 2000)
  net.socket_error(&status, connection.descriptor)
  peer := net.Address{}
  net.peer_address(&status, connection.descriptor, &peer)
  if peer.bytes[2] != local.bytes[2] || peer.bytes[3] != local.bytes[3] { #panic("peer address") }
  _ = net.connection_write(&status, &connection, "ping")
  item := net.PollDescriptor{ descriptor: #cast(net.Descriptor, connection.descriptor), events: net.PollReadable | net.PollError | net.PollHangup }
  if net.poll(&status, #slice(&item, 1), 2000) != 1 || !net.poll_has(&item, net.PollReadable) || item.events != 25 { #panic("poll") }
  buffer: [4]u8
  at: usize = 0
  for at < 4 {
    part := net.connection_read(&status, &connection, buffer[at..])
    if part == 0 { #panic("client read") }
    at += part
  }
  if !bytes.equal(buffer[..], "pong") { #panic("response") }
  net.connection_close(&connection)
  net.connection_close(&connection)
  thread.join(&status, active)
  thread.join(&status, active)
  if thread.id(active) != 0 || sync.load_u64(&shared.count) != 10000 { #panic("join visibility") }
  udp := net.socket(&status, net.AddressFamilyIpv4, net.SocketDatagram, 0)
  defer { net.close(udp) }
  address = net.ipv4(127, 0, 0, 1, 0)
  net.bind_ipv4(&status, udp, &address)
  net.local_address(&status, udp, &local)
  net.nonblocking(&status, udp, true)
  length: u32 = 0
  pending: fail.Status
  _ = net.receive_from(&pending, udp, buffer[..], 0, peer.bytes[..], &length)
  if !net.would_block(&pending.failure) { #panic("would block") }
  _ = net.send_to(&status, udp, buffer[..0], 0, local.bytes[..local.length])
  if net.wait(&status, udp, net.PollReadable, 2000) == 0 { #panic("udp readiness") }
  packet := net.receive_from(&status, udp, buffer[..], 0, peer.bytes[..], &length)
  if packet != 0 || length != 16 { #panic("empty datagram delivery") }
  net.nonblocking(&status, udp, false)
  loopback: [16]u8
  loopback[15] = 1
  ipv6 := net.ipv6(loopback, 0, 0)
  v6 := net.socket(&status, net.AddressFamilyIpv6, net.SocketDatagram, 0)
  defer { net.close(v6) }
  net.bind_ipv6(&status, v6, &ipv6)
  net.local_address(&status, v6, &local)
  if local.length != 28 { #panic("ipv6 bind") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-native-net-') as temporary:
    work = Path(temporary)
    (work/'main.dyn').write_text(SOURCE)
    targets = ['x86_64-linux','aarch64-linux','aarch64-macos','x86_64-windows'] if '--cross' in sys.argv else [None]
    for target in targets:
        for mode in ['--debug','--release']:
            output = work/('probe.exe' if os.name == 'nt' or target == 'x86_64-windows' else 'probe')
            command = [DYN,'build',str(work),mode,'--quiet','--no-cache','--output',str(output)]
            if target: command += ['--target',target]
            subprocess.run(command,check=True,timeout=120)
            if target is None: subprocess.run([str(output)],check=True,timeout=20)
print('PASS native threads/TCP/UDP (debug/release)' if '--cross' not in sys.argv else 'PASS threads/TCP/UDP cross-links; foreign execution requires native CI')
