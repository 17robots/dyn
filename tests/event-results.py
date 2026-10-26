#!/usr/bin/env python3
"""Portable readiness lifecycle, tokens, level triggering, capacity and errors."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/event" event
use "std/net" net
use "std/mem" mem
use "std/errors" errors
fn check(ok: bool) { if !ok { #panic("event readiness") } }
fn main() {
  arena := mem.Arena{}
  scratch := mem.Arena{}
  defer { mem.arena_release(&scratch)
    mem.arena_release(&arena) }
  check(event.open(&arena, 0).kind == errors.Kind.InvalidInput)
  opened := event.open(&arena, 1)
  check(opened.ok)
  queue := opened.value
  check(event.wait(&scratch, &queue, 0).ok)
  socket := net.socket(net.AddressFamilyIpv4, net.SocketDatagram, 0)
  check(socket.ok)
  descriptor := socket.value
  address := net.ipv4(127, 0, 0, 1, 0)
  check(net.bind_ipv4(descriptor, &address).ok)
  local := net.Address{}
  check(net.local_address(descriptor, &local).ok)
  check(net.nonblocking(descriptor, true).ok)
  check(event.add(&queue, descriptor, 0, 0).kind == errors.Kind.InvalidInput)
  check(event.add(&queue, descriptor, event.Readable, 42).ok)
  check(event.add(&queue, descriptor, event.Readable, 9).kind == errors.Kind.AlreadyExists)
  other := net.socket(net.AddressFamilyIpv4, net.SocketDatagram, 0)
  check(other.ok)
  check(event.add(&queue, other.value, event.Readable, 1).kind == errors.Kind.Capacity)
  check(net.close(other.value).ok)
  empty := event.wait(&scratch, &queue, 5)
  check(empty.ok && #len(empty.value) == 0)
  check(net.send_to(descriptor, "x", 0, local.bytes[..local.length]).ok)
  ready := event.wait(&scratch, &queue, 1000)
  check(ready.ok && #len(ready.value) == 1)
  check(ready.value[0].descriptor == descriptor && ready.value[0].token == 42 && (ready.value[0].events & event.Readable) != 0)
  ready = event.wait(&scratch, &queue, 0)
  check(ready.ok && #len(ready.value) == 1)
  check(event.modify(&queue, descriptor, event.Writable, 18446744073709551615).ok)
  ready = event.wait(&scratch, &queue, 1000)
  check(ready.ok && #len(ready.value) == 1 && ready.value[0].token == 18446744073709551615 && (ready.value[0].events & event.Writable) != 0)
  check(event.remove(&queue, descriptor).ok)
  check(event.remove(&queue, descriptor).kind == errors.Kind.NotFound)
  check(event.modify(&queue, descriptor, event.Readable, 0).kind == errors.Kind.NotFound)
  check(event.wait(&scratch, &queue, 0).ok)
  check(event.add(&queue, descriptor, event.Readable, 7).ok)
  ready = event.wait(&scratch, &queue, 0)
  check(ready.ok && #len(ready.value) == 1 && ready.value[0].token == 7)
  check(event.remove(&queue, descriptor).ok)
  check(event.close(&queue).ok && event.close(&queue).ok)
  check(event.wait(&scratch, &queue, 0).kind == errors.Kind.InvalidState)
  // The queue never closes registered descriptors.
  check(net.close(descriptor).ok)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-event-results-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE.replace('  // The queue never closes registered descriptors.', '  fault(&arena, &scratch)\n  // The queue never closes registered descriptors.'))
    (work / 'posix.dyn').write_text('''#target(kernel: linux)
fn fault(arena: *mem.Arena, scratch: *mem.Arena) {
  opened := event.open(arena, 1)
  check(opened.ok)
  queue := opened.value
  failed := event.add(&queue, 2147483647, event.Readable, 0)
  check(!failed.ok && failed.error != 0)
  again := event.wait(scratch, &queue, 0)
  check(!again.ok && again.kind == failed.kind && again.error == failed.error)
  check(event.close(&queue).ok)
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
