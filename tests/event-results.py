#!/usr/bin/env python3
"""Portable readiness lifecycle, tokens, level triggering, capacity and errors."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use event "std/event"
use "std/fail"
use net "std/net"
use mem "std/mem"
fn check(ok: bool) { if !ok { #panic("event readiness") } }
fn kind(status: *const fail.Status) fail.Kind {
  return status.failure.kind
}
fn main() {
  arena := mem.arena_alloc(0)
  scratch := mem.arena_alloc(0)
  defer { mem.arena_release(scratch)
    mem.arena_release(arena) }
  invalid: fail.Status
  _ = event.open(arena, &invalid, 0)
  check(kind(&invalid) == fail.Kind.InvalidInput)
  status := fail.Status{ on_failure: fail.panic_on_failure }
  queue := event.open(arena, &status, 1)
  _ = event.wait(scratch, &status, &queue, 0)
  descriptor := net.socket(&status, net.AddressFamilyIpv4, net.SocketDatagram, 0)
  address := net.ipv4(127, 0, 0, 1, 0)
  net.bind_ipv4(&status, descriptor, &address)
  local := net.Address{}
  net.local_address(&status, descriptor, &local)
  net.nonblocking(&status, descriptor, true)
  no_events: fail.Status
  event.add(&no_events, &queue, descriptor, 0, 0)
  check(kind(&no_events) == fail.Kind.InvalidInput)
  event.add(&status, &queue, descriptor, event.Readable, 42)
  twice: fail.Status
  event.add(&twice, &queue, descriptor, event.Readable, 9)
  check(kind(&twice) == fail.Kind.AlreadyExists)
  other := net.socket(&status, net.AddressFamilyIpv4, net.SocketDatagram, 0)
  full: fail.Status
  event.add(&full, &queue, other, event.Readable, 1)
  check(kind(&full) == fail.Kind.Capacity)
  net.close(other)
  empty := event.wait(scratch, &status, &queue, 5)
  check(empty.len == 0)
  _ = net.send_to(&status, descriptor, "x", 0, local.bytes[..local.length])
  ready := event.wait(scratch, &status, &queue, 1000)
  check(ready.len == 1)
  check(ready[0].descriptor == descriptor && ready[0].token == 42 && (ready[0].events & event.Readable) != 0)
  ready = event.wait(scratch, &status, &queue, 0)
  check(ready.len == 1)
  event.modify(&status, &queue, descriptor, event.Writable, 18446744073709551615)
  ready = event.wait(scratch, &status, &queue, 1000)
  check(ready.len == 1 && ready[0].token == 18446744073709551615 && (ready[0].events & event.Writable) != 0)
  event.remove(&status, &queue, descriptor)
  missing: fail.Status
  event.remove(&missing, &queue, descriptor)
  check(kind(&missing) == fail.Kind.NotFound)
  unknown: fail.Status
  event.modify(&unknown, &queue, descriptor, event.Readable, 0)
  check(kind(&unknown) == fail.Kind.NotFound)
  _ = event.wait(scratch, &status, &queue, 0)
  event.add(&status, &queue, descriptor, event.Readable, 7)
  ready = event.wait(scratch, &status, &queue, 0)
  check(ready.len == 1 && ready[0].token == 7)
  event.remove(&status, &queue, descriptor)
  event.close(&queue)
  event.close(&queue)
  closed: fail.Status
  _ = event.wait(scratch, &closed, &queue, 0)
  check(kind(&closed) == fail.Kind.InvalidState)
  // The queue never closes registered descriptors.
  net.close(descriptor)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-event-results-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE.replace('  // The queue never closes registered descriptors.', '  fault(arena, scratch)\n  // The queue never closes registered descriptors.'))
    (work / 'posix.dyn').write_text('''#target(kernel: linux)
fn fault(arena: *mem.Arena, scratch: *mem.Arena) {
  status: fail.Status
  queue := event.open(arena, &status, 1)
  check(!status.failed)
  event.add(&status, &queue, 2147483647, event.Readable, 0)
  check(status.failed && status.failure.native != 0)
  // A failed change poisons the queue.
  again: fail.Status
  _ = event.wait(scratch, &again, &queue, 0)
  check(again.failure.kind == fail.Kind.InvalidState)
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
