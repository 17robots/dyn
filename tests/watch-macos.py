#!/usr/bin/env python3
"""FSEvents file events, bounded callback queue and teardown; cross-link elsewhere."""
import os
from pathlib import Path
import platform
import selectors
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
NATIVE = platform.system() == 'Darwin' and platform.machine() == 'arm64'
SOURCE = r'''use "./watch" watch
use "std/io" io
use "std/time" time
use "std/bytes" bytes
fn require(ok: bool, message: []const u8) { if !ok { #panic(message) } }
fn stage(name: []const u8) { _ = io.println(io.stdout(),"{}",name) }
fn await_event(state: *watch.Watcher, id: i32, name: []const u8, mask: u32, renamed: bool) {
  for attempt in 0..1500 {
    result := watch.next(state)
    require(result.status != watch.Status.Error,"event error")
    if result.status == watch.Status.Event && result.event.watch == id && (result.event.mask & mask) != 0 && bytes.equal(result.event.name,name) {
      if renamed { require(result.event.cookie == 0 && result.event.rescan && state.rescan_required,"rename rescan") }
      return
    }
    _ = time.sleep(time.Millisecond*10)
  }
  #panic("event timed out")
}
fn main() {
  watch.audit_callbacks()
  empty := watch.Watcher{}
  require(watch.close(&empty).ok,"default close")
  require(watch.next(&empty).status == watch.Status.Error,"default next")
  storage: [1024]u8 = []
  failed := watch.open(storage[..271])
  require(!failed.ok && watch.close(&failed.watcher).ok,"short buffer")
  opened := watch.open(storage[..])
  require(opened.ok,"FSEvents open")
  defer { _ = watch.close(&opened.watcher) }
  require(!watch.add(&opened.watcher,"missing-directory",watch.Changes).ok,"missing path")
  require(!watch.add(&opened.watcher,"existing",watch.Changes).ok,"file path")
  added := watch.add(&opened.watcher,".",watch.Changes)
  other := watch.add(&opened.watcher,"other",watch.Changes)
  require(added.ok && other.ok && added.value != other.value,"multiple watches")
  require(watch.add(&opened.watcher,".",watch.Changes).value == added.value,"repeat add identity")
  stage("create")
  await_event(&opened.watcher,added.value,"café-😀",watch.Create,false)
  stage("write")
  await_event(&opened.watcher,added.value,"existing",watch.Modify,false)
  stage("rename")
  await_event(&opened.watcher,added.value,"renamed",watch.MoveTo,true)
  watch.acknowledge_rescan(&opened.watcher)
  require(!opened.watcher.rescan_required,"rescan acknowledgement")
  stage("delete")
  await_event(&opened.watcher,added.value,"renamed",watch.Delete,false)
  stage("other")
  await_event(&opened.watcher,other.value,"second",watch.Create,false)
  require(watch.remove(&opened.watcher,added.value).ok,"remove")
  require(!watch.remove(&opened.watcher,added.value).ok,"stale remove")
  stage("removed")
  await_event(&opened.watcher,other.value,"third",watch.Create,false)
  for attempt in 0..50 {
    result := watch.next(&opened.watcher)
    require(result.status != watch.Status.Error,"after remove")
    require(result.status != watch.Status.Event || result.event.watch != added.value,"removed watch delivery")
    _ = time.sleep(time.Millisecond*10)
  }
  stage("close")
  // Each close invalidates pending callbacks before freeing/reusing contexts.
  for iteration in 0..16 {
    pending := watch.open(storage[..])
    require(pending.ok,"pending open")
    require(watch.add(&pending.watcher,".",watch.Changes).ok,"pending add")
    _ = time.sleep(time.Millisecond*5)
    require(watch.close(&pending.watcher).ok && watch.close(&pending.watcher).ok,"pending close")
  }
  require(watch.close(&opened.watcher).ok,"final close")
  stage("passed")
}
'''
# Compile this helper into a temporary copy of the real module. It exercises the
# actual private callback/queue without manufacturing filesystem overflow or
# exporting testing APIs. The nonzero stream value is compared, never called.
AUDIT = r'''
pub fn audit_callbacks() {
  allocation := mem.arena_create(#sizeof(State))
  if !allocation.ok { #panic("audit allocation") }
  defer { _ = mem.arena_release(&allocation.arena) }
  pushed := mem.arena_try_push(&allocation.arena,#sizeof(State),#alignof(State))
  if !pushed.ok { #panic("audit backing") }
  state := #cast(*State) pushed.memory
  slot := &state.slots[0]
  slot.owner = state slot.id = 7 slot.mask = Changes
  slot.stream = #cast(rawptr) #cast(usize) 1
  root := "/watched"
  slot.length = #len(root)
  for i in 0..#len(root) { slot.root[i] = root[i] }
  output: [1024]u8 = []
  watcher := Watcher{state:state,storage:output[..]}
  name_storage: [128]u8 = []
  path := c.string_from_bytes(name_storage[..],"/watched/café-😀")
  pointers: [1]*const u8 = [path.value]
  flags: [1]u32 = [256]
  ids: [1]u64 = [1]
  callback(nil,#cast(rawptr) slot,1,#cast(rawptr) &pointers[0],&flags[0],&ids[0])
  item := next(&watcher)
  if item.status != Status.Event || item.event.watch != 7 || item.event.mask != Create || !bytes.equal(item.event.name,"café-😀") { #panic("callback Unicode child") }
  for i in 0..128 { name_storage[i] = 0 }
  if !bytes.equal(item.event.name,"café-😀") { #panic("callback retained borrowed native path") }
  path = c.string_from_bytes(name_storage[..],"/watched/nested/file")
  pointers[0] = path.value
  callback(nil,#cast(rawptr) slot,1,#cast(rawptr) &pointers[0],&flags[0],&ids[0])
  if next(&watcher).status != Status.Empty { #panic("recursive event leaked") }
  path = c.string_from_bytes(name_storage[..],"/watched/file")
  pointers[0] = path.value
  flags[0] = 2048
  callback(nil,#cast(rawptr) slot,1,#cast(rawptr) &pointers[0],&flags[0],&ids[0])
  item = next(&watcher)
  if !item.event.rescan || item.event.cookie != 0 || item.event.mask != (MoveFrom|MoveTo) { #panic("callback rename") }
  flags[0] = 4
  callback(nil,#cast(rawptr) slot,1,#cast(rawptr) &pointers[0],&flags[0],&ids[0])
  if !next(&watcher).event.rescan || !watcher.rescan_required { #panic("kernel dropped events") }
  for next(&watcher).status == Status.Event {}
  acknowledge_rescan(&watcher)
  for i in 0..80 { publish(slot,"overflow",Create,false) }
  if !next(&watcher).event.rescan || !watcher.rescan_required { #panic("bounded queue overflow") }
  count: usize = 0
  for next(&watcher).status == Status.Event { count += 1 }
  if count != 63 { #panic("queue capacity") }
  publish(slot,"reused",Create,false)
  if !bytes.equal(next(&watcher).event.name,"reused") { #panic("queue wrap/reuse") }
  watcher.storage = output[..1]
  publish(slot,"long",Create,false)
  if !next(&watcher).event.rescan { #panic("short caller output") }
}
'''

def wait_stage(process, expected):
    with selectors.DefaultSelector() as ready:
        ready.register(process.stdout, selectors.EVENT_READ)
        if not ready.select(20):
            raise AssertionError(f'timeout waiting for {expected}')
    line = process.stdout.readline().decode().strip()
    if line != expected:
        raise AssertionError(f'expected {expected}, got {line!r}')

with tempfile.TemporaryDirectory(prefix='dyn-watch-macos-') as temporary:
    root = Path(temporary)
    source = root / 'src'
    module = source / 'watch'
    module.mkdir(parents=True)
    (source / 'main.dyn').write_text(SOURCE)
    (module / 'macos.dyn').write_text((ROOT/'std/fs/watch/macos.dyn').read_text()+AUDIT)
    for mode in ('--debug', '--release'):
        output = root/'program'
        command = [DYN,'build',str(source),'--target','aarch64-macos',mode,'--no-cache','--quiet','--output',str(output)]
        if not NATIVE and not shutil.which('ld64.lld'):
            command.append('--no-link')
        subprocess.run(command,check=True,timeout=90)
        if not NATIVE:
            continue
        directory = root / mode[2:]
        directory.mkdir()
        (directory/'other').mkdir()
        (directory/'existing').write_text('before')
        process = subprocess.Popen([str(output)],cwd=directory,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
        try:
            wait_stage(process,'create')
            (directory/'café-😀').write_text('created')
            wait_stage(process,'write')
            with (directory/'existing').open('a') as changed:
                changed.write('updated'); changed.flush(); os.fsync(changed.fileno())
            wait_stage(process,'rename')
            (directory/'existing').rename(directory/'renamed')
            wait_stage(process,'delete')
            (directory/'renamed').unlink()
            wait_stage(process,'other')
            (directory/'other/second').write_text('other')
            wait_stage(process,'removed')
            (directory/'removed').write_text('no delivery')
            (directory/'other/third').write_text('still live')
            wait_stage(process,'close')
            for i in range(200):
                (directory/f'pending-{i}').write_text('pending')
            wait_stage(process,'passed')
            _, error = process.communicate(timeout=10)
            assert process.returncode == 0, error.decode()
        finally:
            if process.poll() is None:
                process.kill()
            _, error = process.communicate(timeout=10)
            if process.returncode:
                print(error.decode(),end='')
print('PASS macOS FSEvents native events/callback queue/teardown (debug/release)' if NATIVE
      else 'PASS macOS FSEvents cross-build (native execution pending)')
