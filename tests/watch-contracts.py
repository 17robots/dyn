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

SOURCE = r'''use watch "std/fs/watch"
use fs "std/fs"
use io "std/io"
use bytes "std/bytes"
fn require(ok: bool, message: []const u8) { if !ok { #panic(message) } }
// failed with code (the system's, or 0) when the watcher failed.
struct Got { value: watch.Event, found: bool, failed: bool, code: isize }
fn code(err: io.IoErr) isize {
  case err {
    .System(native) => { return native }
    _ => { return 0 }
  }
}
fn next(state: *watch.Watcher) Got {
  value := watch.next(state) catch err { return Got{ failed: true, code: code(err) } }
  return Got{ value: value, found: !state.ended }
}
fn event(state: *watch.Watcher) watch.Event {
  got := next(state)
  require(!got.failed && got.found, "expected an event")
  return got.value
}
fn empty(state: *watch.Watcher) bool {
  got := next(state)
  return !got.failed && !got.found
}
fn add_fails(state: *watch.Watcher, path: []const u8) bool {
  _ = watch.add(state, path, watch.Create) catch { return true }
  return false
}
fn remove_fails(state: *watch.Watcher, id: i32) bool {
  watch.remove(state, id) catch { return true }
  return false
}
fn create(path: []const u8) {
  opened := fs.create(path) catch { #panic("create file") }
  fs.close(&opened)
}
fn malformed(storage: []u8, used: usize) {
  // Buffered records are the public seam; this never reads or owns descriptor 0.
  state := watch.Watcher{ descriptor: 0, storage: storage, used: used }
  result := next(&state)
  require(result.failed && result.code == -74, "malformed event")
  require(state.offset == 0 && !state.rescan_required, "malformed event changed state")
}
// ENOSPC for too little event storage.
fn open_fails_capacity(storage: []u8) bool {
  _ = watch.open(storage) catch err {
    case err {
      .Capacity => { return true }
      _ => { return false }
    }
  }
  return false
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
    opened := watch.open(storage[..]) catch {
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
  require(next(&unopened).failed, "read unopened")
  storage: [272]u8
  for length in 0..272 {
    require(open_fails_capacity(storage[..length]), "short backing")
    require(#syscall(72,0,1,0) >= 0, "failed open closed stdin")
  }
  state := watch.open(storage[..]) catch { #panic("open watcher") }
  defer { watch.close(&state) }
  require(empty(&state), "empty nonblocking read")
  require(add_fails(&state,""), "empty path")
  invalid: [3]u8 = ['.',0,'x']
  require(add_fails(&state,invalid[..]), "embedded NUL path")
  require(add_fails(&state,"missing-directory"), "missing path")
  added := watch.add(&state,".",watch.Create) catch { #panic("add watch") }
  create("first")
  create("second")
  first := event(&state)
  require(first.watch == added && (first.mask & watch.Create) != 0 && bytes.equal(first.name,"first"), "first create event")
  used := state.used
  second := event(&state)
  require(bytes.equal(second.name,"second"), "second create event")
  require(state.used == used && bytes.equal(first.name,"first"), "borrowed name changed without refill")
  require(empty(&state), "drained watcher")
  watch.remove(&state,added) catch { #panic("remove watch") }
  ignored := event(&state)
  require(ignored.watch == added && (ignored.mask & watch.Ignored) != 0, "removed watch ignored event")
  create("third")
  require(empty(&state), "removed watch still reports events")
  require(remove_fails(&state,added), "remove stale watch")
  _ = watch.add(&state,".",watch.Create) catch { #panic("add watch") }
  create("fourth")
  _ = event(&state)
  descriptor := state.descriptor
  watch.close(&state)
  require(#syscall(72,descriptor,1,0) == -9, "descriptor leaked")
  watch.close(&state)
  require(next(&state).failed, "read closed watcher")
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
