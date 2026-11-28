#!/usr/bin/env python3
"""Portable readiness lifecycle, tokens, level triggering, capacity and errors."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import private_display  # hides the desktop display; see tests/private_display.py

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use event "std/event"
use "std/bytes"
use "std/io"
use net "std/net"
use mem "std/mem"
fn check(ok: bool) { if !ok { #panic("event readiness") } }
fn is(err: io.IoErr, text: []const u8) bool {
  return bytes.equal(io.text(err), text)
}
fn open_err(arena: *mem.Arena, capacity: usize) io.IoErr {
  _ = event.open(arena, capacity) catch err { return err }
  #panic("event.open unexpectedly succeeded")
}
fn add_err(queue: *event.Queue, descriptor: isize, events: u32, token: u64) io.IoErr {
  event.add(queue, descriptor, events, token) catch err { return err }
  #panic("event.add unexpectedly succeeded")
}
fn modify_err(queue: *event.Queue, descriptor: isize, events: u32, token: u64) io.IoErr {
  event.modify(queue, descriptor, events, token) catch err { return err }
  #panic("event.modify unexpectedly succeeded")
}
fn remove_err(queue: *event.Queue, descriptor: isize) io.IoErr {
  event.remove(queue, descriptor) catch err { return err }
  #panic("event.remove unexpectedly succeeded")
}
fn wait_err(scratch: *mem.Arena, queue: *event.Queue) io.IoErr {
  _ = event.wait(scratch, queue, 0) catch err { return err }
  #panic("event.wait unexpectedly succeeded")
}
fn wait(scratch: *mem.Arena, queue: *event.Queue, timeout: i32) []event.Event {
  return event.wait(scratch, queue, timeout) catch { #panic("event.wait") }
}
fn main() {
  arena := mem.arena_alloc(0)
  scratch := mem.arena_alloc(0)
  defer { mem.arena_release(scratch)
    mem.arena_release(arena) }
  check(is(open_err(arena, 0), "invalid input"))
  queue := event.open(arena, 1) catch { #panic("event.open") }
  _ = wait(scratch, &queue, 0)
  descriptor := net.socket(net.AddressFamilyIpv4, net.SocketDatagram, 0) catch { #panic("net.socket") }
  address := net.ipv4(127, 0, 0, 1, 0)
  net.bind_ipv4(descriptor, &address) catch { #panic("net.bind_ipv4") }
  local := net.Address{}
  net.local_address(descriptor, &local) catch { #panic("net.local_address") }
  net.nonblocking(descriptor, true) catch { #panic("net.nonblocking") }
  check(is(add_err(&queue, descriptor, 0, 0), "invalid input"))
  event.add(&queue, descriptor, event.Readable, 42) catch { #panic("event.add") }
  check(is(add_err(&queue, descriptor, event.Readable, 9), "already exists"))
  other := net.socket(net.AddressFamilyIpv4, net.SocketDatagram, 0) catch { #panic("net.socket") }
  check(is(add_err(&queue, other, event.Readable, 1), "too large or out of space"))
  net.close(other)
  empty := wait(scratch, &queue, 5)
  check(empty.len == 0)
  _ = net.send_to(descriptor, "x", 0, local.bytes[..local.length]) catch { #panic("net.send_to") }
  ready := wait(scratch, &queue, 1000)
  check(ready.len == 1)
  check(ready[0].descriptor == descriptor && ready[0].token == 42 && (ready[0].events & event.Readable) != 0)
  ready = wait(scratch, &queue, 0)
  check(ready.len == 1)
  event.modify(&queue, descriptor, event.Writable, 18446744073709551615) catch { #panic("event.modify") }
  ready = wait(scratch, &queue, 1000)
  check(ready.len == 1 && ready[0].token == 18446744073709551615 && (ready[0].events & event.Writable) != 0)
  event.remove(&queue, descriptor) catch { #panic("event.remove") }
  check(is(remove_err(&queue, descriptor), "not found"))
  check(is(modify_err(&queue, descriptor, event.Readable, 0), "not found"))
  _ = wait(scratch, &queue, 0)
  event.add(&queue, descriptor, event.Readable, 7) catch { #panic("event.add") }
  ready = wait(scratch, &queue, 0)
  check(ready.len == 1 && ready[0].token == 7)
  event.remove(&queue, descriptor) catch { #panic("event.remove") }
  event.close(&queue)
  event.close(&queue)
  check(is(wait_err(scratch, &queue), "invalid input"))
  // The queue never closes registered descriptors.
  net.close(descriptor)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-event-results-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE.replace('  // The queue never closes registered descriptors.', '  fault(arena, scratch)\n  // The queue never closes registered descriptors.'))
    (work / 'posix.dyn').write_text('''#target(kernel: linux)
fn fault(arena: *mem.Arena, scratch: *mem.Arena) {
  queue := event.open(arena, 1) catch { #panic("event.open") }
  failed := false
  event.add(&queue, 2147483647, event.Readable, 0) catch { failed = true }
  check(failed)
  // A failed change poisons the queue.
  check(is(wait_err(scratch, &queue), "invalid input"))
  event.close(&queue)
}
''')
    (work / 'macos.dyn').write_text((work / 'posix.dyn').read_text().replace('kernel: linux', 'kernel: darwin'))
    (work / 'windows.dyn').write_text('''#target(kernel: windows)
fn fault(arena: *mem.Arena, scratch: *mem.Arena) {
  _ = arena
  _ = scratch
}
''')
    for mode in ('--debug', '--release'):
        output = work / 'program'
        subprocess.run([DYN, 'build', str(work), mode, '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=300)
        subprocess.run([str(output)], check=True, timeout=20)
    for target in ('aarch64-linux', 'riscv64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows'):
        output = work / target
        subprocess.run([DYN, 'build', str(work), '--target', target, '--quiet', '--output', str(output)], check=True, timeout=300)
        emulator = {'aarch64-linux': 'qemu-aarch64', 'riscv64-linux': 'qemu-riscv64', 'x86_64-windows': 'wine'}.get(target)
        if emulator and shutil.which(emulator):
            subprocess.run([emulator, str(output)], check=True, timeout=60)
print('PASS event results: lifecycle, readiness, tokens, capacity, modify/remove and cross-builds')
