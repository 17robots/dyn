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
use mem "std/mem"
use "std/sync"
use "std/bytes"
struct Context { listener: net.Listener, ready: sync.AtomicU32, count: sync.AtomicU64 }
fn worker(shared: *Context) isize {
  for sync.load_u32(&shared.ready) == 0 { thread.yield_now() }
  connection := net.listener_accept(&shared.listener) catch { #panic("net.listener_accept") }
  defer { net.connection_close(&connection) }
  buffer: [4]u8
  at: usize = 0
  for at < 4 {
    part := net.connection_read(&connection, buffer[at..]) catch { #panic("net.connection_read") }
    if part == 0 { #panic("server read") }
    at += part
  }
  if !bytes.equal(buffer[..], "ping") { #panic("request") }
  _ = net.connection_write(&connection, "pong") catch { #panic("net.connection_write") }
  for i in 0..10000 { _ = sync.fetch_add_u64(&shared.count, 1) }
  return 0
}
fn receive_would_block(udp: isize, buffer: []u8, address: []u8, length: *u32) bool {
  _ = net.receive_from(udp, buffer, 0, address, length) catch err { return net.would_block(err) }
  return false
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
  shared := Context{ listener: net.tcp_listen_ipv4(&address, 4) catch { #panic("listen") } }
  defer { net.listener_close(&shared.listener) }
  local := net.Address{}
  net.local_address(shared.listener.descriptor, &local) catch { #panic("net.local_address") }
  if local.length != 16 { #panic("local address") }
  port := (#cast(u16, local.bytes[2]) << 8) | #cast(u16, local.bytes[3])
  if port == 0 { #panic("ephemeral port") }
  active:=thread.spawn(arena, &status, stack[..], worker, &shared)
  if active==nil || thread.id(active)==0 { #panic("active ownership") }
  sync.store_u32(&shared.ready, 1)
  address = net.ipv4(127, 0, 0, 1, port)
  connection := net.tcp_connect_ipv4(&address) catch { #panic("net.tcp_connect_ipv4") }
  net.send_timeout(connection.descriptor, 2000) catch { #panic("net.send_timeout") }
  net.receive_timeout(connection.descriptor, 2000) catch { #panic("net.receive_timeout") }
  net.socket_error(connection.descriptor) catch { #panic("net.socket_error") }
  peer := net.Address{}
  net.peer_address(connection.descriptor, &peer) catch { #panic("net.peer_address") }
  if peer.bytes[2] != local.bytes[2] || peer.bytes[3] != local.bytes[3] { #panic("peer address") }
  _ = net.connection_write(&connection, "ping") catch { #panic("net.connection_write") }
  item := net.PollDescriptor{ descriptor: #cast(net.Descriptor, connection.descriptor), events: net.PollReadable | net.PollError | net.PollHangup }
  if (net.poll(#slice(&item, 1), 2000) catch 0) != 1 || !net.poll_has(&item, net.PollReadable) || item.events != 25 { #panic("poll") }
  buffer: [4]u8
  at: usize = 0
  for at < 4 {
    part := net.connection_read(&connection, buffer[at..]) catch { #panic("net.connection_read") }
    if part == 0 { #panic("client read") }
    at += part
  }
  if !bytes.equal(buffer[..], "pong") { #panic("response") }
  net.connection_close(&connection)
  net.connection_close(&connection)
  thread.join(&status, active)
  thread.join(&status, active)
  if thread.id(active) != 0 || sync.load_u64(&shared.count) != 10000 { #panic("join visibility") }
  udp := net.socket(net.AddressFamilyIpv4, net.SocketDatagram, 0) catch { #panic("net.socket") }
  defer { net.close(udp) }
  address = net.ipv4(127, 0, 0, 1, 0)
  net.bind_ipv4(udp, &address) catch { #panic("net.bind_ipv4") }
  net.local_address(udp, &local) catch { #panic("net.local_address") }
  net.nonblocking(udp, true) catch { #panic("net.nonblocking") }
  length: u32 = 0
  if !receive_would_block(udp, buffer[..], peer.bytes[..], &length) { #panic("would block") }
  _ = net.send_to(udp, buffer[..0], 0, local.bytes[..local.length]) catch { #panic("net.send_to") }
  if (net.wait(udp, net.PollReadable, 2000) catch 0) == 0 { #panic("udp readiness") }
  packet := net.receive_from(udp, buffer[..], 0, peer.bytes[..], &length) catch { #panic("net.receive_from") }
  if packet != 0 || length != 16 { #panic("empty datagram delivery") }
  net.nonblocking(udp, false) catch { #panic("net.nonblocking") }
  loopback: [16]u8
  loopback[15] = 1
  ipv6 := net.ipv6(loopback, 0, 0)
  v6 := net.socket(net.AddressFamilyIpv6, net.SocketDatagram, 0) catch { #panic("net.socket") }
  defer { net.close(v6) }
  net.bind_ipv6(v6, &ipv6) catch { #panic("net.bind_ipv6") }
  net.local_address(v6, &local) catch { #panic("net.local_address") }
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
