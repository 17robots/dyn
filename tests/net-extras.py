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
use io "std/io"
fn check(ok: bool) {
  if !ok { #panic("network extras") }
}
fn invalid(err: io.IoErr) bool {
  case err {
    .InvalidInput => { return true }
    _ => { return false }
  }
}
fn listen_rejected(address: *const net.UnixAddress) bool {
  listener := net.unix_listen(address, 1) catch err { return invalid(err) }
  net.listener_close(&listener)
  return false
}
fn ready(descriptor: isize, milliseconds: i32) bool {
  events := net.wait(descriptor, net.PollReadable, milliseconds) catch { return false }
  return events != 0
}
fn exchange(listener: *net.Listener, connection: *net.Connection) {
  peer := net.listener_accept(listener) catch { #panic("net.listener_accept") }
  _ = net.connection_write(connection, "ping") catch { #panic("net.connection_write") }
  check(ready(peer.descriptor, 1000))
  buffer: [4]u8
  got := net.connection_read(&peer, buffer[..]) catch { #panic("net.connection_read") }
  check(got == 4 && buffer[0] == 112 && buffer[3] == 103)
  net.connection_close(&peer)
  net.connection_close(connection)
  net.listener_close(listener)
}
fn main() {
  check(net.unix("").length == 0 && net.unix("bad\x00path").length == 0)
  oversized: [108]u8
  check(net.unix(oversized[..]).length == 0)
  empty := net.unix("")
  check(listen_rejected(&empty))
  empty.length = 111
  bind := false
  net.bind_unix(-1, &empty) catch err { bind = invalid(err) }
  check(bind)
  connect := false
  net.connect_unix(-1, &empty) catch err { connect = invalid(err) }
  check(connect)
  path := net.unix("dyn-net-extras.sock")
  listener := net.unix_listen(&path, 4) catch { #panic("net.unix_listen") }
  connection := net.unix_connect(&path) catch { #panic("net.unix_connect") }
  exchange(&listener, &connection)
  loopback: [16]u8
  loopback[15] = 1
  address := net.ipv6(loopback, 0, 0)
  listener = net.tcp_listen_ipv6(&address, 4) catch { #panic("net.tcp_listen_ipv6") }
  local := net.Address{}
  net.local_address(listener.descriptor, &local) catch { #panic("net.local_address") }
  check(local.length == 28)
  port := (#cast(u16, local.bytes[2]) << 8) | #cast(u16, local.bytes[3])
  address = net.ipv6(loopback, port, 0)
  connection = net.tcp_connect_ipv6(&address) catch { #panic("net.tcp_connect_ipv6") }
  exchange(&listener, &connection)
  descriptor := net.socket(net.AddressFamilyIpv4, net.SocketDatagram, 0) catch { #panic("net.socket") }
  bound := net.ipv4(0, 0, 0, 0, 0)
  net.bind_ipv4(descriptor, &bound) catch { #panic("net.bind_ipv4") }
  net.local_address(descriptor, &local) catch { #panic("net.local_address") }
  port = (#cast(u16, local.bytes[2]) << 8) | #cast(u16, local.bytes[3])
  group: [4]u8 = [239, 255, 42, 17]
  interface: [4]u8 = [127, 0, 0, 1]
  bad: [4]u8 = [127, 0, 0, 1]
  not_group := false
  net.multicast_join_ipv4(descriptor, bad, interface) catch err { not_group = invalid(err) }
  check(not_group)
  net.multicast_join_ipv4(descriptor, group, interface) catch { #panic("net.multicast_join_ipv4") }
  net.multicast_interface_ipv4(descriptor, interface) catch { #panic("net.multicast_interface_ipv4") }
  net.multicast_ttl_ipv4(descriptor, 1) catch { #panic("net.multicast_ttl_ipv4") }
  net.multicast_loop_ipv4(descriptor, true) catch { #panic("net.multicast_loop_ipv4") }
  destination := net.ipv4(239, 255, 42, 17, port)
  _ = net.send_to(descriptor, "group", 0, destination.bytes[..]) catch { #panic("net.send_to") }
  check(ready(descriptor, 2000))
  data: [8]u8
  received := net.receive(descriptor, data[..], 0) catch { #panic("net.receive") }
  check(received == 5 && data[0] == 103 && data[4] == 112)
  net.multicast_leave_ipv4(descriptor, group, interface) catch { #panic("net.multicast_leave_ipv4") }
  net.multicast_loop_ipv4(descriptor, false) catch { #panic("net.multicast_loop_ipv4") }
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
