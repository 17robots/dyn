#!/usr/bin/env python3
"""Real inotify ownership/events and bounded malformed-record contracts."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
if sys.platform != 'linux':
    print('SKIP Linux filesystem watch contracts')
    raise SystemExit(0)

import resource

def bounded_descriptors():
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64 if soft == resource.RLIM_INFINITY else min(64, soft), hard))

SOURCE = r'''use "std/fs/watch" watch
use "std/fail"
use "std/fs" fs
use "std/io" io
use "std/bytes" bytes
fn require(ok: bool, message: []const u8) { if !ok { #panic(message) } }
struct Got { value: watch.Event, found: bool, failure: fail.Failure }
fn next(state: *watch.Watcher) Got {
  status: fail.Status
  value := watch.next(&status, state)
  return Got{ value: value, found: !state.ended, failure: status.failure }
}
fn event(state: *watch.Watcher) watch.Event {
  got := next(state)
  require(got.failure.kind == fail.Kind.Ok && got.found, "expected an event")
  return got.value
}
fn empty(state: *watch.Watcher) bool {
  got := next(state)
  return got.failure.kind == fail.Kind.Ok && !got.found
}
fn add_fails(state: *watch.Watcher, path: []const u8) bool {
  status: fail.Status
  _ = watch.add(&status, state, path, watch.Create)
  return status.failed
}
fn remove_fails(state: *watch.Watcher, id: i32) bool {
  status: fail.Status
  watch.remove(&status, state, id)
  return status.failed
}
fn create(path: []const u8) {
  status: fail.Status
  opened := fs.create(&status, path)
  require(!status.failed, "create file")
  fs.close(&opened)
}
fn malformed(storage: []u8, used: usize) {
  // Buffered records are the public seam; this never reads or owns descriptor 0.
  state := watch.Watcher{ descriptor: 0, storage: storage, used: used }
  result := next(&state)
  require(result.failure.kind != fail.Kind.Ok && result.failure.native == -74, "malformed event")
  require(state.offset == 0 && !state.rescan_required, "malformed event changed state")
}
fn records() {
  storage: [64]u8
  for length in 1..16 { malformed(storage[..],length) }
  // Length field claims more bytes than the buffered record contains.
  storage[12] = 255
  storage[13] = 255
  storage[14] = 255
  storage[15] = 255
  malformed(storage[..],16)
  storage[12] = 4
  storage[13] = 0
  storage[14] = 0
  storage[15] = 0
  for i in 16..20 { storage[i] = 'a' }
  malformed(storage[..],20)
  storage[19] = 0
  state := watch.Watcher{ descriptor: 0, storage: storage[..], used: 20 }
  named := event(&state)
  require(bytes.equal(named.name,"aaa"), "terminated event name")
  storage = [0,0,0,0,0,64,0,0]
  for i in 0..4 { storage[i] = 255 }
  state = watch.Watcher{ descriptor: 0, storage: storage[..], used: 16 }
  overflow := event(&state)
  require(overflow.watch == -1 && overflow.rescan && state.rescan_required, "overflow requires rescan")
  watch.acknowledge_rescan(&state)
  require(!state.rescan_required, "acknowledge rescan")
}
fn exhausted_open() {
  storage: [272]u8
  states: [128]watch.Watcher
  count: usize = 0
  failed: bool = false
  for count < 128 {
    status: fail.Status
    opened := watch.open(&status, storage[..])
    if status.failed {
      require(status.failure.native < 0, "open failure error")
      require(!opened.active, "failed syscall owns stdin")
      watch.close(&opened)
      require(#syscall(72,0,1,0) >= 0, "syscall failure closed stdin")
      failed = true
      break
    }
    states[count] = opened
    count += 1
  }
  for i in 0..count { watch.close(&states[i]) }
  require(failed, "descriptor limit did not force open failure")
}
fn main() {
  unopened := watch.Watcher{}
  require(!unopened.active, "default watcher is open")
  watch.close(&unopened)
  watch.close(&unopened)
  require(#syscall(72,0,1,0) >= 0, "unopened close clobbered stdin")
  require(add_fails(&unopened,"."), "add unopened")
  require(remove_fails(&unopened,0), "remove unopened")
  require(next(&unopened).failure.kind != fail.Kind.Ok, "read unopened")
  storage: [272]u8
  for length in 0..272 {
    status: fail.Status
    failed := watch.open(&status, storage[..length])
    require(status.failed && status.failure.native == -28, "short backing")
    watch.close(&failed)
    require(#syscall(72,0,1,0) >= 0, "failed open closed stdin")
  }
  status := fail.Status{ on_failure: fail.panic_on_failure }
  state := watch.open(&status, storage[..])
  defer { watch.close(&state) }
  require(empty(&state), "empty nonblocking read")
  require(add_fails(&state,""), "empty path")
  invalid: [3]u8 = ['.',0,'x']
  require(add_fails(&state,invalid[..]), "embedded NUL path")
  require(add_fails(&state,"missing-directory"), "missing path")
  added := watch.add(&status,&state,".",watch.Create)
  create("first")
  create("second")
  first := event(&state)
  require(first.watch == added && (first.mask & watch.Create) != 0 && bytes.equal(first.name,"first"), "first create event")
  used := state.used
  second := event(&state)
  require(bytes.equal(second.name,"second"), "second create event")
  require(state.used == used && bytes.equal(first.name,"first"), "borrowed name changed without refill")
  require(empty(&state), "drained watcher")
  watch.remove(&status,&state,added)
  ignored := event(&state)
  require(ignored.watch == added && (ignored.mask & watch.Ignored) != 0, "removed watch ignored event")
  create("third")
  require(empty(&state), "removed watch still reports events")
  require(remove_fails(&state,added), "remove stale watch")
  _ = watch.add(&status,&state,".",watch.Create)
  create("fourth")
  _ = event(&state)
  descriptor := state.descriptor
  watch.close(&state)
  require(#syscall(72,descriptor,1,0) == -9, "descriptor leaked")
  watch.close(&state)
  require(next(&state).failure.kind != fail.Kind.Ok, "read closed watcher")
  records()
  exhausted_open()
}'''
with tempfile.TemporaryDirectory(prefix='dyn-watch-contracts-') as temporary:
    project = Path(temporary) / 'source'
    project.mkdir()
    (project / 'main.dyn').write_text(SOURCE)
    for release in (False, True):
        output = Path(temporary) / 'program'
        subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet',
                        '--output', str(output)] + (['--release'] if release else []),
                       check=True, timeout=90)
        directory = Path(temporary) / ('release' if release else 'debug')
        directory.mkdir()
        subprocess.run([str(output)], cwd=directory, stdin=subprocess.DEVNULL,
                       check=True, timeout=15, preexec_fn=bounded_descriptors)
print('PASS watcher ownership, actual directory events, overflow/malformed records (debug/release)')
