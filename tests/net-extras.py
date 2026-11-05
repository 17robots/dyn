#!/usr/bin/env python3
"""Unix streams, IPv6 loopback and IPv4 multicast through the public API."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/net" net
use "std/io" errors
fn check(ok: bool) {
  if !ok { #panic("network extras") }
}
fn exchange(listener: *net.Listener, connection: *net.Connection) {
  accepted := net.listener_accept(listener)
  check(accepted.failure.kind == errors.Kind.Ok)
  peer := accepted.value
  check(net.connection_write(connection, "ping").failure.kind == errors.Kind.Ok)
  check(net.wait(peer.descriptor, net.PollReadable, 1000).value != 0)
  buffer: [4]u8 = []
  got := net.connection_read(&peer, buffer[..])
  check(got.failure.kind == errors.Kind.Ok && got.value == 4 && buffer[0] == 112 && buffer[3] == 103)
  check(net.connection_close(&peer).failure.kind == errors.Kind.Ok)
  check(net.connection_close(connection).failure.kind == errors.Kind.Ok)
  check(net.listener_close(listener).failure.kind == errors.Kind.Ok)
}
fn main() {
  check(net.unix("").length == 0 && net.unix("bad\x00path").length == 0)
  oversized: [108]u8 = []
  check(net.unix(oversized[..]).length == 0)
  invalid := net.unix("")
  check(net.unix_listen(&invalid, 1).failure.kind == errors.Kind.InvalidInput)
  invalid.length = 111
  check(net.bind_unix(-1, &invalid).failure.kind == errors.Kind.InvalidInput)
  check(net.connect_unix(-1, &invalid).failure.kind == errors.Kind.InvalidInput)
  path := net.unix("dyn-net-extras.sock")
  opened := net.unix_listen(&path, 4)
  check(opened.failure.kind == errors.Kind.Ok)
  listener := opened.value
  connected := net.unix_connect(&path)
  check(connected.failure.kind == errors.Kind.Ok)
  connection := connected.value
  exchange(&listener, &connection)

  loopback: [16]u8 = []
  loopback[15] = 1
  address := net.ipv6(loopback, 0, 0)
  opened = net.tcp_listen_ipv6(&address, 4)
  check(opened.failure.kind == errors.Kind.Ok)
  listener = opened.value
  local := net.Address{}
  check(net.local_address(listener.descriptor, &local).failure.kind == errors.Kind.Ok && local.length == 28)
  port := (#cast(u16, local.bytes[2]) << 8) | #cast(u16, local.bytes[3])
  address = net.ipv6(loopback, port, 0)
  connected = net.tcp_connect_ipv6(&address)
  check(connected.failure.kind == errors.Kind.Ok)
  connection = connected.value
  exchange(&listener, &connection)

  socket := net.socket(net.AddressFamilyIpv4, net.SocketDatagram, 0)
  check(socket.failure.kind == errors.Kind.Ok)
  descriptor := socket.value
  bound := net.ipv4(0, 0, 0, 0, 0)
  check(net.bind_ipv4(descriptor, &bound).failure.kind == errors.Kind.Ok)
  check(net.local_address(descriptor, &local).failure.kind == errors.Kind.Ok)
  port = (#cast(u16, local.bytes[2]) << 8) | #cast(u16, local.bytes[3])
  group: [4]u8 = [239, 255, 42, 17]
  interface: [4]u8 = [127, 0, 0, 1]
  bad: [4]u8 = [127, 0, 0, 1]
  check(net.multicast_join_ipv4(descriptor, bad, interface).failure.kind == errors.Kind.InvalidInput)
  check(net.multicast_join_ipv4(descriptor, group, interface).failure.kind == errors.Kind.Ok)
  check(net.multicast_interface_ipv4(descriptor, interface).failure.kind == errors.Kind.Ok)
  check(net.multicast_ttl_ipv4(descriptor, 1).failure.kind == errors.Kind.Ok)
  check(net.multicast_loop_ipv4(descriptor, true).failure.kind == errors.Kind.Ok)
  destination := net.ipv4(239, 255, 42, 17, port)
  check(net.send_to(descriptor, "group", 0, destination.bytes[..]).failure.kind == errors.Kind.Ok)
  ready := net.wait(descriptor, net.PollReadable, 2000)
  check(ready.failure.kind == errors.Kind.Ok && ready.value != 0)
  data: [8]u8 = []
  received := net.receive(descriptor, data[..], 0)
  check(received.failure.kind == errors.Kind.Ok && received.value == 5 && data[0] == 103 && data[4] == 112)
  check(net.multicast_leave_ipv4(descriptor, group, interface).failure.kind == errors.Kind.Ok)
  check(net.multicast_loop_ipv4(descriptor, false).failure.kind == errors.Kind.Ok)
  check(net.close(descriptor).failure.kind == errors.Kind.Ok)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-net-extras-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE)
    for mode in ('--debug', '--release'):
        output = work / 'program'
        subprocess.run([DYN, 'build', str(work), mode, '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=300)
        subprocess.run([str(output)], cwd=work, check=True, timeout=20)
        (work / 'dyn-net-extras.sock').unlink()
    for target in ('aarch64-linux', 'riscv64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows'):
        output = work / target
        subprocess.run([DYN, 'build', str(work), '--target', target, '--quiet', '--output', str(output)], check=True, timeout=300)
        emulator = {'aarch64-linux': 'qemu-aarch64', 'riscv64-linux': 'qemu-riscv64'}.get(target)
        if emulator and shutil.which(emulator):
            subprocess.run([emulator, str(output)], cwd=work, check=True, timeout=30)
            (work / 'dyn-net-extras.sock').unlink()
print('PASS net extras: Unix/IPv6 streams, IPv4 multicast, validation; debug/release and cross-builds')
