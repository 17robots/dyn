#!/usr/bin/env python3
"""Real socket regressions for ownership, empty datagrams, and peer disconnects."""
from contextlib import ExitStack
import os
from pathlib import Path
import socket
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
if sys.platform != 'linux':
    print('SKIP Linux networking contracts')
    raise SystemExit(0)

CASES = {
    'unopened-connection': '''use io "std/io"
use "std/net"
fn main() {
  connection := net.Connection{}
  net.connection_close(&connection)
  if #syscall(72, 0, 1, 0) < 0 { #panic("closed stdin") }
}
''',
    'unopened-listener': '''use io "std/io"
use "std/net"
fn main() {
  listener := net.Listener{}
  net.listener_close(&listener)
  if #syscall(72, 0, 1, 0) < 0 { #panic("closed stdin") }
}
''',
    'failed-connection': '''use "std/net"
fn check_failed() {
  if #syscall(72, 0, 1, 0) < 0 { #panic("failed connection closed stdin") }
}
fn connect_fails(address: *const net.Ipv4Address) bool {
  connection := net.tcp_connect_ipv4(address) catch { return true }
  net.connection_close(&connection)
  return false
}
fn accept_fails(listener: *net.Listener) bool {
  connection := net.listener_accept(listener) catch { return true }
  net.connection_close(&connection)
  return false
}
fn main() {
  address := net.ipv4(127, 0, 0, 1, 1)
  address.bytes[0] = 255
  if !connect_fails(&address) { #panic("connection unexpectedly succeeded") }
  check_failed()
  listener := net.Listener{}
  if !accept_fails(&listener) { #panic("accept on a closed listener succeeded") }
  check_failed()
  // Positive descriptor validation must fail without closing anything else.
  listener.descriptor = 2147483647
  listener.active = true
  if !accept_fails(&listener) { #panic("accept on an invalid descriptor succeeded") }
  check_failed()
}
''',
    'failed-listener': '''use "std/net"
fn listen_fails(address: *const net.Ipv4Address) bool {
  listener := net.tcp_listen_ipv4(address, 1) catch { return true }
  net.listener_close(&listener)
  return false
}
fn main() {
  address := net.ipv4(127, 0, 0, 1, 1)
  address.bytes[0] = 255
  if !listen_fails(&address) { #panic("listener unexpectedly succeeded") }
  if #syscall(72, 0, 1, 0) < 0 { #panic("failed listener closed stdin") }
}
''',
    'empty-datagram': '''use "std/net"
fn send_fails(descriptor: isize, address: []const u8) bool {
  _ = net.send_to(descriptor, "", 0, address) catch { return true }
  return false
}
fn main() {
  descriptor := net.socket(net.AddressFamilyIpv4, net.SocketDatagram, 0) catch { #panic("net.socket") }
  defer { net.close(descriptor) }
  address := net.ipv4(127, 0, 0, 1, 0)
  net.bind_ipv4(descriptor, &address) catch { #panic("net.bind_ipv4") }
  bound := net.Address{}
  net.local_address(descriptor, &bound) catch { #panic("net.local_address") }
  net.nonblocking(descriptor, true) catch { #panic("net.nonblocking") }
  sent := net.send_to(descriptor, "", 0, bound.bytes[..bound.length]) catch { #panic("net.send_to") }
  if sent != 0 { #panic("send empty") }
  ready := net.wait(descriptor, net.PollReadable, 1000) catch { #panic("net.wait") }
  if ready == 0 { #panic("empty datagram dropped") }
  // An empty datagram still validates the destination and socket.
  if !send_fails(-1, bound.bytes[..bound.length]) { #panic("invalid socket accepted") }
  if !send_fails(descriptor, "") { #panic("invalid address accepted") }
  buffer: [1]u8
  peer: [128]u8
  length: u32 = 0
  received := net.receive_from(descriptor, buffer[..], 0, peer[..], &length) catch { #panic("net.receive_from") }
  if received != 0 || length != 16 { #panic("receive empty") }
  sent = net.send_to(descriptor, "x", 0, bound.bytes[..bound.length]) catch { #panic("net.send_to") }
  if sent != 1 { #panic("send byte") }
  ready = net.wait(descriptor, net.PollReadable, 1000) catch { #panic("net.wait") }
  if ready == 0 { #panic("byte datagram dropped") }
  received = net.receive_from(descriptor, buffer[..], 0, peer[..], &length) catch { #panic("net.receive_from") }
  if received != 1 || buffer[0] != 'x' { #panic("receive byte") }
}
''',
}

for operation, expression in {
    'send': '_ = net.send(SOCKET_FD, "x", 0) catch err { return err }',
    'connection-write': 'net.connection_write(connection, "x") catch err { return err }',
    'send-to': '_ = net.send_to(SOCKET_FD, "x", 0, address.bytes[..]) catch err { return err }',
}.items():
    CASES['disconnected-' + operation] = '''use "std/io"
use "std/net"
fn attempt(connection: *net.Connection, address: *const net.Ipv4Address) io.IoErr {
  EXPRESSION
  #panic("write to a disconnected peer succeeded")
}
fn main() {
  connection := net.connection_from_descriptor(SOCKET_FD)
  address := net.ipv4(127, 0, 0, 1, 1)
  case attempt(&connection, &address) {
    .System(code) => { if code != -32 { #panic("expected EPIPE") } }
    _ => { #panic("expected EPIPE") }
  }
}
'''.replace('EXPRESSION', expression)

SIGNAL_HELPER = r"""
#define _POSIX_C_SOURCE 200809L
#include <signal.h>
#include <sys/time.h>
#include <unistd.h>
static volatile sig_atomic_t signals, deliver;
static int descriptors[2];
static void interrupt_wait(int signal) {
    (void)signal;
    ++signals;
    if (signals == deliver) { char byte = 'x'; (void)write(descriptors[1], &byte, 1); }
    if (signals == 100) { struct itimerval timer = {0}; setitimer(ITIMER_REAL, &timer, 0); }
}
int net_audit_start(int readiness) {
    if (pipe(descriptors)) return -1;
    signals = 0;
    deliver = readiness ? 5 : 0;
    struct sigaction action = {0};
    action.sa_handler = interrupt_wait;
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGALRM, &action, 0)) return -1;
    struct itimerval timer = {{0, 10000}, {0, 10000}};
    if (setitimer(ITIMER_REAL, &timer, 0)) return -1;
    return descriptors[0];
}
int net_audit_stop(void) {
    struct itimerval timer = {0};
    setitimer(ITIMER_REAL, &timer, 0);
    close(descriptors[0]); close(descriptors[1]);
    return signals;
}
"""
WAIT_SOURCE = r'''use "std/net"
use "std/time"
extern fn start "net_audit_start"(readiness: i32) i32
extern fn stop "net_audit_stop"() i32
fn main() {
  descriptor := start(READY)
  if descriptor < 0 { #panic("signal helper") }
  queue := net.event_queue() catch { #panic("net.event_queue") }
  defer { net.close(queue) }
  net.event_add(queue, #cast(isize, descriptor), net.EventReadable, 42) catch { #panic("net.event_add") }
  items: [1]net.PollDescriptor = [net.PollDescriptor{ descriptor: descriptor, events: net.PollReadable }]
  events: [1]net.Event
  before := time.monotonic_now()
  outcome := OPERATION
  after := time.monotonic_now()
  duration := time.elapsed(before, after)
  signals := stop()
  if TIMEOUT == 100 {
    if outcome != 0 || duration < 80000000 || duration > 750000000 || signals < 2 {
      #panic("interrupted wait restarted its deadline")
    }
  }
  else if TIMEOUT == 0 {
    if outcome != 0 || duration > 250000000 { #panic("zero timeout blocked") }
  }
  else {
    if outcome != 1 || signals < 2 || duration > 750000000 { #panic("interrupted readiness lost") }
    VERIFY
  }
}
'''

failures = []
with tempfile.TemporaryDirectory(prefix='dyn-net-contracts-') as temporary, ExitStack() as stack:
    for name, source in CASES.items():
        descriptors = ()
        if name.startswith('disconnected-'):
            if name == 'disconnected-send-to':
                # TCP permits sendto's destination argument on connected streams.
                with socket.socket() as listener:
                    listener.bind(('127.0.0.1', 0))
                    listener.listen(1)
                    sender = socket.create_connection(listener.getsockname(), timeout=2)
                    peer, _ = listener.accept()
                peer.close()
                assert sender.recv(1) == b''
                sender.shutdown(socket.SHUT_WR)
            else:
                sender, peer = socket.socketpair()
                peer.close()
            stack.enter_context(sender)
            descriptors = (sender.fileno(),)
            source = source.replace('SOCKET_FD', str(sender.fileno()))
        project = Path(temporary) / name
        project.mkdir()
        (project / 'main.dyn').write_text(source)
        for release in (False, True):
            output = project / 'program'
            subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet',
                            '--output', str(output)] + (['--release'] if release else []),
                           check=True, timeout=90)
            result = subprocess.run([str(output)], stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=10,
                                    pass_fds=descriptors)
            if result.returncode:
                failures.append(f'{name} ({"release" if release else "debug"}): exit {result.returncode}: {result.stderr.strip()}')
    helper = Path(temporary) / 'signals.c'
    helper.write_text(SIGNAL_HELPER)
    library = Path(temporary) / 'signals.so'
    subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), '-std=c11', '-O2', '-shared', '-fPIC',
                    str(helper), '-o', str(library)], check=True, timeout=30)
    for kind, operation, verify in (
        ('poll', 'net.poll(items[..], TIMEOUT) catch { #panic("net.poll") }',
         'if !net.poll_has(&items[0], net.PollReadable) { #panic("poll readiness") }'),
        ('epoll', 'net.event_wait(queue, events[..], TIMEOUT) catch { #panic("net.event_wait") }',
         'if net.event_data(&events[0]) != 42 { #panic("epoll readiness") }'),
    ):
        for timeout in (100, 1000, -1, 0):
            project = Path(temporary) / f'interrupted-{kind}-{timeout}'
            project.mkdir()
            source = WAIT_SOURCE.replace('OPERATION', operation).replace('VERIFY', verify)
            source = source.replace('TIMEOUT', str(timeout)).replace('READY', '1' if timeout in (1000, -1) else '0')
            (project / 'main.dyn').write_text(source)
            for mode in ('--debug', '--release'):
                output = project / 'program'
                subprocess.run([DYN, 'build', str(project), mode, '--quiet', '--no-cache',
                                '--link', str(library), '--output', str(output)], check=True, timeout=90)
                result = subprocess.run([str(output)], capture_output=True, text=True, timeout=5)
                if result.returncode:
                    failures.append(f'{project.name} {mode}: {result.returncode}: {result.stderr.strip()}')
if failures:
    raise SystemExit('\n'.join(failures))
print('PASS network ownership, UDP delivery, disconnected writes, and interrupted deadlines/readiness (debug/release)')
