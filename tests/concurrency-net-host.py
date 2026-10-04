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
SOURCE = '''use "std/net"
use "std/thread"
use "std/sync"
use "std/bytes"
struct Context { listener: net.Listener, ready: sync.AtomicU32, count: sync.AtomicU64 }
fn worker(context: rawptr) isize {
  shared := #cast(*Context) context
  for sync.load_u32(&shared.ready) == 0 { _ = thread.yield_now() }
  accepted := net.listener_accept(&shared.listener)
  if !accepted.ok { #panic("accept") }
  connection := accepted.connection
  defer { _ = net.connection_close(&connection) }
  buffer: [4]u8 = []
  at: usize = 0
  for at < 4 {
    part := net.connection_read(&connection, buffer[at..])
    if !part.ok || part.value <= 0 { #panic("server read") }
    at += #cast(usize) part.value
  }
  if !bytes.equal(buffer[..], "ping") { #panic("request") }
  if !net.connection_write(&connection, "pong").ok { #panic("server write") }
  for i in 0..10000 { _ = sync.fetch_add_u64(&shared.count, 1) }
  return 0
}
fn main() {
  idle := thread.Thread{}
  if thread.join(&idle) != 0 || thread.id(&idle) != 0 { #panic("empty join") }
  stack: [131072]u8 = []
  if thread.spawn(&idle, stack[..0], &worker, nil) >= 0 { #panic("short stack") }
  address := net.ipv4(127, 0, 0, 1, 0)
  opened := net.tcp_listen_ipv4(&address, 4)
  if !opened.ok { #panic("listen") }
  shared := Context{ listener: opened.listener }
  defer { _ = net.listener_close(&shared.listener) }
  local := net.Address{}
  if !net.local_address(shared.listener.descriptor, &local).ok || local.length != 16 { #panic("local address") }
  port := (#cast(u16) local.bytes[2] << 8) | #cast(u16) local.bytes[3]
  if port == 0 { #panic("ephemeral port") }
  active := thread.Thread{}
  if thread.spawn(&active, stack[..], &worker, #cast(rawptr) &shared) < 0 { #panic("spawn") }
  if thread.id(&active) == 0 || thread.spawn(&active, stack[..], &worker, #cast(rawptr) &shared) >= 0 { #panic("active ownership") }
  sync.store_u32(&shared.ready, 1)
  address = net.ipv4(127, 0, 0, 1, port)
  connected := net.tcp_connect_ipv4(&address)
  if !connected.ok { #panic("connect") }
  connection := connected.connection
  if !net.send_timeout(connection.descriptor, 2000).ok || !net.receive_timeout(connection.descriptor, 2000).ok { #panic("timeouts") }
  if !net.socket_error(connection.descriptor).ok { #panic("socket error") }
  peer := net.Address{}
  if !net.peer_address(connection.descriptor, &peer).ok || peer.bytes[2] != local.bytes[2] || peer.bytes[3] != local.bytes[3] { #panic("peer address") }
  if !net.connection_write(&connection, "ping").ok { #panic("request write") }
  item := net.PollDescriptor{ descriptor: #cast(net.Descriptor) connection.descriptor, events: net.PollReadable | net.PollError | net.PollHangup }
  if net.poll((&item)[..1], 2000).value != 1 || !net.poll_has(&item, net.PollReadable) || item.events != 25 { #panic("poll") }
  buffer: [4]u8 = []
  at: usize = 0
  for at < 4 {
    part := net.connection_read(&connection, buffer[at..])
    if !part.ok || part.value <= 0 { #panic("client read") }
    at += #cast(usize) part.value
  }
  if !bytes.equal(buffer[..], "pong") { #panic("response") }
  if !net.connection_close(&connection).ok || net.connection_close(&connection).ok { #panic("connection close") }
  if thread.join(&active) != 0 || thread.join(&active) != 0 || thread.id(&active) != 0 || sync.load_u64(&shared.count) != 10000 { #panic("join visibility") }
  udp := net.socket(net.AddressFamilyIpv4, net.SocketDatagram, 0)
  if !udp.ok { #panic("udp socket") }
  defer { _ = net.close(udp.value) }
  address = net.ipv4(127, 0, 0, 1, 0)
  if !net.bind_ipv4(udp.value, &address).ok || !net.local_address(udp.value, &local).ok { #panic("udp bind") }
  if !net.nonblocking(udp.value, true).ok { #panic("nonblocking") }
  length: u32 = 0
  pending := net.receive_from(udp.value, buffer[..], 0, peer.bytes[..], &length)
  if !net.would_block(&pending) { #panic("would block") }
  if !net.send_to(udp.value, buffer[..0], 0, local.bytes[..local.length]).ok { #panic("empty datagram") }
  if net.wait(udp.value, net.PollReadable, 2000).value <= 0 { #panic("udp readiness") }
  packet := net.receive_from(udp.value, buffer[..], 0, peer.bytes[..], &length)
  if !packet.ok || packet.value != 0 || length != 16 { #panic("empty datagram delivery") }
  if !net.nonblocking(udp.value, false).ok { #panic("blocking restore") }
  loopback: [16]u8 = [] loopback[15] = 1
  ipv6 := net.ipv6(loopback, 0, 0)
  v6 := net.socket(net.AddressFamilyIpv6, net.SocketDatagram, 0)
  if !v6.ok { #panic("ipv6 socket") }
  defer { _ = net.close(v6.value) }
  if !net.bind_ipv6(v6.value, &ipv6).ok || !net.local_address(v6.value, &local).ok || local.length != 28 { #panic("ipv6 bind") }
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
