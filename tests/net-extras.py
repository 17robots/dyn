#!/usr/bin/env python3
"""Unix streams, IPv6 loopback and IPv4 multicast through the public API."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use net "std/net"
use "std/fail"
fn check(ok: bool) {
  if !ok { #panic("network extras") }
}
fn invalid(status: *const fail.Status) bool {
  return status.failed && status.failure.kind == fail.Kind.InvalidInput
}
fn exchange(status: *fail.Status, listener: *net.Listener, connection: *net.Connection) {
  peer := net.listener_accept(status, listener)
  _ = net.connection_write(status, connection, "ping")
  check(net.wait(status, peer.descriptor, net.PollReadable, 1000) != 0)
  buffer: [4]u8
  got := net.connection_read(status, &peer, buffer[..])
  check(!status.failed && got == 4 && buffer[0] == 112 && buffer[3] == 103)
  net.connection_close(&peer)
  net.connection_close(connection)
  net.listener_close(listener)
}
fn main() {
  check(net.unix("").length == 0 && net.unix("bad\x00path").length == 0)
  oversized: [108]u8
  check(net.unix(oversized[..]).length == 0)
  empty := net.unix("")
  rejected: fail.Status
  _ = net.unix_listen(&rejected, &empty, 1)
  check(invalid(&rejected))
  empty.length = 111
  bind: fail.Status
  net.bind_unix(&bind, -1, &empty)
  check(invalid(&bind))
  connect: fail.Status
  net.connect_unix(&connect, -1, &empty)
  check(invalid(&connect))
  status := fail.Status{ on_failure: fail.panic_on_failure }
  path := net.unix("dyn-net-extras.sock")
  listener := net.unix_listen(&status, &path, 4)
  connection := net.unix_connect(&status, &path)
  exchange(&status, &listener, &connection)
  loopback: [16]u8
  loopback[15] = 1
  address := net.ipv6(loopback, 0, 0)
  listener = net.tcp_listen_ipv6(&status, &address, 4)
  local := net.Address{}
  net.local_address(&status, listener.descriptor, &local)
  check(local.length == 28)
  port := (#cast(u16, local.bytes[2]) << 8) | #cast(u16, local.bytes[3])
  address = net.ipv6(loopback, port, 0)
  connection = net.tcp_connect_ipv6(&status, &address)
  exchange(&status, &listener, &connection)
  descriptor := net.socket(&status, net.AddressFamilyIpv4, net.SocketDatagram, 0)
  bound := net.ipv4(0, 0, 0, 0, 0)
  net.bind_ipv4(&status, descriptor, &bound)
  net.local_address(&status, descriptor, &local)
  port = (#cast(u16, local.bytes[2]) << 8) | #cast(u16, local.bytes[3])
  group: [4]u8 = [239, 255, 42, 17]
  interface: [4]u8 = [127, 0, 0, 1]
  bad: [4]u8 = [127, 0, 0, 1]
  not_group: fail.Status
  net.multicast_join_ipv4(&not_group, descriptor, bad, interface)
  check(invalid(&not_group))
  net.multicast_join_ipv4(&status, descriptor, group, interface)
  net.multicast_interface_ipv4(&status, descriptor, interface)
  net.multicast_ttl_ipv4(&status, descriptor, 1)
  net.multicast_loop_ipv4(&status, descriptor, true)
  destination := net.ipv4(239, 255, 42, 17, port)
  _ = net.send_to(&status, descriptor, "group", 0, destination.bytes[..])
  check(net.wait(&status, descriptor, net.PollReadable, 2000) != 0)
  data: [8]u8
  received := net.receive(&status, descriptor, data[..], 0)
  check(received == 5 && data[0] == 103 && data[4] == 112)
  net.multicast_leave_ipv4(&status, descriptor, group, interface)
  net.multicast_loop_ipv4(&status, descriptor, false)
  net.close(descriptor)
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
