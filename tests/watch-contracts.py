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
use "std/fs" fs
use "std/bytes" bytes
fn require(ok: bool, message: []const u8) { if !ok { #panic(message) } }
fn create(path: []const u8) {
  opened := fs.create(path)
  require(opened.ok, "create file")
  require(fs.close(&opened.file).ok, "close file")
}
fn malformed(storage: []u8, used: usize) {
  // Buffered records are the public seam; this never reads or owns descriptor 0.
  state := watch.Watcher{ descriptor: 0, storage: storage, used: used }
  result := watch.next(&state)
  require(result.status == watch.Status.Error && result.error == -74, "malformed event")
  require(state.offset == 0 && !state.rescan_required, "malformed event changed state")
}
fn records() {
  storage: [64]u8 = []
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
  event := watch.next(&state)
  require(event.status == watch.Status.Event && bytes.equal(event.event.name,"aaa"), "terminated event name")
  storage = [0,0,0,0,0,64,0,0]
  for i in 0..4 { storage[i] = 255 }
  state = watch.Watcher{ descriptor: 0, storage: storage[..], used: 16 }
  event = watch.next(&state)
  require(event.status == watch.Status.Event && event.event.watch == -1 && event.event.rescan && state.rescan_required, "overflow requires rescan")
  watch.acknowledge_rescan(&state)
  require(!state.rescan_required, "acknowledge rescan")
}
fn exhausted_open() {
  storage: [272]u8 = []
  states: [128]watch.Watcher = []
  count: usize = 0
  failed: bool = false
  for count < 128 {
    opened := watch.open(storage[..])
    if !opened.ok {
      require(opened.error < 0, "open failure error")
      require(opened.watcher.descriptor == -1, "failed syscall owns stdin")
      require(watch.close(&opened.watcher).ok, "close syscall failure")
      require(#syscall(72,0,1,0) >= 0, "syscall failure closed stdin")
      failed = true
      break
    }
    states[count] = opened.watcher
    count += 1
  }
  for i in 0..count { require(watch.close(&states[i]).ok, "close exhausted watchers") }
  require(failed, "descriptor limit did not force open failure")
}
fn main() {
  unopened := watch.Watcher{}
  require(unopened.descriptor == -1, "default watcher is open")
  require(watch.close(&unopened).ok && watch.close(&unopened).ok, "unopened close")
  require(#syscall(72,0,1,0) >= 0, "unopened close clobbered stdin")
  require(!watch.add(&unopened,".",watch.Create).ok, "add unopened")
  require(!watch.remove(&unopened,0).ok, "remove unopened")
  require(watch.next(&unopened).status == watch.Status.Error, "read unopened")
  storage: [272]u8 = []
  for length in 0..272 {
    failed := watch.open(storage[..length])
    require(!failed.ok && failed.error == -28, "short backing")
    require(watch.close(&failed.watcher).ok, "close failed open")
    require(#syscall(72,0,1,0) >= 0, "failed open closed stdin")
  }
  opened := watch.open(storage[..])
  require(opened.ok, "open watcher")
  state := opened.watcher
  defer { _ = watch.close(&state) }
  require(watch.next(&state).status == watch.Status.Empty, "empty nonblocking read")
  require(!watch.add(&state,"",watch.Create).ok, "empty path")
  invalid: [3]u8 = ['.',0,'x']
  require(!watch.add(&state,invalid[..],watch.Create).ok, "embedded NUL path")
  require(!watch.add(&state,"missing-directory",watch.Create).ok, "missing path")
  added := watch.add(&state,".",watch.Create)
  require(added.ok, "add watch")
  create("first")
  create("second")
  first := watch.next(&state)
  require(first.status == watch.Status.Event && first.event.watch == added.value && (first.event.mask & watch.Create) != 0 && bytes.equal(first.event.name,"first"), "first create event")
  used := state.used
  second := watch.next(&state)
  require(second.status == watch.Status.Event && bytes.equal(second.event.name,"second"), "second create event")
  require(state.used == used && bytes.equal(first.event.name,"first"), "borrowed name changed without refill")
  require(watch.next(&state).status == watch.Status.Empty, "drained watcher")
  require(watch.remove(&state,added.value).ok, "remove watch")
  ignored := watch.next(&state)
  require(ignored.status == watch.Status.Event && ignored.event.watch == added.value && (ignored.event.mask & watch.Ignored) != 0, "removed watch ignored event")
  create("third")
  require(watch.next(&state).status == watch.Status.Empty, "removed watch still reports events")
  require(!watch.remove(&state,added.value).ok, "remove stale watch")
  require(watch.add(&state,".",watch.Create).ok, "re-add watch")
  create("fourth")
  require(watch.next(&state).status == watch.Status.Event, "re-added watch")
  descriptor := state.descriptor
  require(watch.close(&state).ok, "close watcher")
  require(#syscall(72,descriptor,1,0) == -9, "descriptor leaked")
  require(watch.close(&state).ok, "repeated close")
  require(watch.next(&state).status == watch.Status.Error, "read closed watcher")
  records()
  exhausted_open()
}
'''
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
