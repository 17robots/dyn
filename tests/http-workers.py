#!/usr/bin/env python3
"""Linux worker lifecycle plus isolated shutdown/spawn/join fault injection."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
ENV = dict(os.environ, DYN_SDK=str(ROOT))
COMMON = '''use "std/net/http" http
use "std/net" net
use "std/mem" mem
use "std/errors" errors
use "std/thread" thread
use "std/sync" sync
use "MODULE" workers
fn handler(response: *http.Response, request: *const http.Request) http.Result {
  _ = response _ = request
  return http.Result{ ok: true }
}
'''
NATIVE = COMMON.replace('MODULE', 'std/net/http/concurrent') + r'''
fn main() {
  nodes: [4096]u8 = [] arena := mem.arena_from_buffer(nodes[..])
  pool: [2]workers.Worker = []
  receive: [8192]u8 = [] stacks: [262144]u8 = []
  workers.stop(pool[..])
  zero := workers.join(pool[..])
  if !zero.ok || zero.kind != errors.Kind.None || zero.error != 0 { #panic("zero lifecycle") }
  listener := http.Listener{}
  for size in [0, 255] {
    bad := workers.start(&arena, pool[..], &listener, receive[..], 4096, stacks[..], #cast(usize, size), &handler)
    if bad.ok || bad.kind != errors.Kind.InvalidInput || bad.error != 0 || bad.started != 0 || mem.arena_mark(&arena) != 0 { #panic("validation") }
  }
  bad := workers.start(&arena, pool[..0], &listener, receive[..], 4096, stacks[..], 131072, &handler)
  if bad.ok || bad.kind != errors.Kind.InvalidInput { #panic("empty validation") }
  address := net.ipv4(127, 0, 0, 1, 0)
  listening := net.tcp_listen_ipv4(&address, 4)
  if !listening.ok { #panic("listen") }
  listener = listening.value
  started := workers.start_context(&arena, pool[..], &listener, receive[..], 4096, stacks[..], 131072, &handler, nil)
  if !started.ok || started.started != 2 || pool[0].thread == nil || pool[0].thread == pool[1].thread { #panic("start") }
  busy := workers.start(&arena, pool[..], &listener, receive[..], 4096, stacks[..], 131072, &handler)
  if busy.ok || busy.kind != errors.Kind.InvalidState || busy.error != 0 { #panic("busy") }
  bound := net.Address{}
  if !net.local_address(listener.descriptor, &bound).ok { #panic("local address") }
  for i in 0..16 { address.bytes[i] = bound.bytes[i] }
  client := net.tcp_connect_ipv4(&address)
  if !client.ok { #panic("connect") }
  connection := client.value
  // One worker blocks in a request read, the other in accept. Every process
  // has a Python timeout, including this synchronization loop.
  active := false
  for !active {
    for *worker in pool {
      sync.lock(&worker.control)
      if worker.active_socket { active = true }
      sync.unlock(&worker.control)
    }
    _ = thread.yield_now()
  }
  workers.stop(pool[..])
  done := workers.join(pool[..])
  if !done.ok || done.started != 2 || pool[0].thread != nil || pool[1].thread != nil { #panic("join") }
  _ = net.connection_close(&connection)
  _ = net.listener_close(&listener)
  workers.stop(pool[..])
  if !workers.join(pool[..]).ok { #panic("repeated join") }
}
'''
MOCK_THREAD = r'''
use "std/mem" mem
use "std/errors" errors
pub struct Thread { index: usize }
pub struct SpawnResult { value: *Thread, ok: bool, kind: errors.Kind, error: isize }
pub struct Result { ok: bool, kind: errors.Kind, error: isize }
pub struct State { spawns: usize, joins: usize, fail_at: usize, fail_join: bool }
pub state: State
pub fn spawn(arena: *mem.Arena, stack: []u8, entry: fn(rawptr) isize, context: rawptr) SpawnResult {
  _ = stack _ = entry _ = context
  state.spawns += 1
  if state.fail_at == state.spawns { return SpawnResult{ kind: errors.Kind.Capacity, error: -12 } }
  node := mem.push(Thread, arena)
  node.index = state.spawns
  return SpawnResult{ value: node, ok: true }
}
pub fn join(node: *Thread) Result {
  state.joins += 1
  if state.fail_join && node.index == 1 { return Result{ kind: errors.Kind.System, error: -5 } }
  return Result{ ok: true }
}
'''
MOCK_NET = r'''
pub const ShutdownBoth: isize = 2
pub calls: usize
pub last: isize
pub fn shutdown(descriptor: isize, mode: isize) isize {
  _ = mode calls += 1 last = descriptor return 0
}
'''
MOCK = COMMON.replace('MODULE', './workers').replace('use "std/thread" thread\n', '') + r'''
use "./mock_thread" mock
use "./mock_net" counter
fn main() {
  nodes: [4096]u8 = [] arena := mem.arena_from_buffer(nodes[..])
  pool: [3]workers.Worker = []
  receive: [3072]u8 = [] stacks: [768]u8 = []
  workers.stop(pool[..])
  if counter.calls != 0 { #panic("zero worker shutdown") }
  // Descriptor zero is valid when explicitly owned.
  pool[0].active_socket = true
  workers.stop(pool[..])
  if counter.calls != 1 || counter.last != 0 { #panic("owned fd zero") }
  pool[0].active_socket = false
  listener := http.Listener{ descriptor: 55, active: true }
  mock.state = mock.State{ fail_at: 3 }
  failed := workers.start(&arena, pool[..], &listener, receive[..], 1024, stacks[..], 256, &handler)
  if failed.ok || failed.kind != errors.Kind.Capacity || failed.error != -12 || failed.started != 2 { #panic("spawn failure result") }
  if mock.state.joins != 2 || counter.calls != 3 || pool[0].thread != nil || pool[1].thread != nil { #panic("rollback drain") }
  mock.state = mock.State{}
  started := workers.start(&arena, pool[..], &listener, receive[..], 1024, stacks[..], 256, &handler)
  if !started.ok { #panic("mock start") }
  pool[0].error = workers.Result{ kind: errors.Kind.InvalidInput, error: 0 }
  pool[1].error = workers.Result{ kind: errors.Kind.System, error: -9 }
  done := workers.join(pool[..])
  if done.ok || done.kind != errors.Kind.InvalidInput || done.error != 0 || done.started != 3 || mock.state.joins != 3 { #panic("first native zero error/all joins") }
  mock.state = mock.State{ fail_join: true }
  _ = workers.start(&arena, pool[..], &listener, receive[..], 1024, stacks[..], 256, &handler)
  done = workers.join(pool[..])
  if done.ok || done.error != -5 || done.started != 2 || mock.state.joins != 3 || pool[0].thread == nil { #panic("failed join retains node/all joins") }
  mock.state.fail_join = false
  if !workers.join(pool[..]).ok { #panic("retry join") }
}
'''


def run(work, source, mode):
    (work / 'main.dyn').write_text(source)
    binary = work / 'probe'
    subprocess.run([DYN, 'build', str(work), '--' + mode, '--quiet', '--no-cache',
                    '--output', str(binary)], env=ENV, check=True, timeout=120)
    subprocess.run([str(binary)], env=ENV, check=True, timeout=15)


def main():
    if platform.system() != 'Linux':
        print('SKIP: Linux HTTP workers')
        return
    with tempfile.TemporaryDirectory(prefix='dyn-http-workers-') as temporary:
        work = Path(temporary)
        implementation = (ROOT / 'std/net/http/concurrent/concurrent.dyn').read_text()
        for mode in ('debug', 'release'):
            run(work, NATIVE, mode)
            (work / 'mock_thread').mkdir(exist_ok=True)
            (work / 'mock_thread/mock_thread.dyn').write_text(MOCK_THREAD)
            (work / 'mock_net').mkdir(exist_ok=True)
            (work / 'mock_net/mock_net.dyn').write_text(MOCK_NET)
            (work / 'workers').mkdir(exist_ok=True)
            (work / 'workers/workers.dyn').write_text(implementation.replace(
                '"std/thread"', '"../mock_thread"').replace('"std/net"', '"../mock_net"'))
            run(work, MOCK, mode)
            print('PASS HTTP workers native lifecycle, validation, shutdown ownership, rollback, all joins ' + mode, flush=True)


if __name__ == '__main__':
    main()
