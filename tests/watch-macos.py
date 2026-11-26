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
SOURCE = r'''use watch "./watch"
use "std/fail"
use io "std/io"
use time "std/time"
use bytes "std/bytes"
fn require(ok: bool, message: []const u8) { if !ok { #panic(message) } }
fn stage(name: []const u8) { io.println("{}",name) }
fn await_event(state: *watch.Watcher, id: i32, name: []const u8, mask: u32, renamed: bool) {
  status: fail.Status
  for attempt in 0..1500 {
    result := watch.next(&status, state)
    require(!status.failed,"event error")
    if !state.ended && result.watch == id && (result.mask & mask) != 0 && bytes.equal(result.name,name) {
      if renamed { require(result.cookie == 0 && result.rescan && state.rescan_required,"rename rescan") }
      return
    }
    time.sleep(time.Millisecond*10)
  }
  #panic("event timed out")
}
fn added(state: *watch.Watcher, path: []const u8) i32 {
  status: fail.Status
  id := watch.add(&status, state, path, watch.Changes)
  require(!status.failed,"add")
  return id
}
fn rejected(state: *watch.Watcher, path: []const u8) bool {
  status: fail.Status
  _ = watch.add(&status, state, path, watch.Changes)
  return status.failed
}
fn removed(state: *watch.Watcher, id: i32) bool {
  status: fail.Status
  watch.remove(&status, state, id)
  return !status.failed
}
fn main() {
  watch.audit_callbacks()
  empty := watch.Watcher{}
  watch.close(&empty)
  unopened: fail.Status
  _ = watch.next(&unopened, &empty)
  require(unopened.failed,"default next")
  storage: [1024]u8
  short: fail.Status
  failed := watch.open(&short, storage[..271])
  watch.close(&failed)
  require(short.failed,"short buffer")
  status: fail.Status
  opened := watch.open(&status, storage[..])
  require(!status.failed,"FSEvents open")
  defer { watch.close(&opened) }
  require(rejected(&opened,"missing-directory"),"missing path")
  require(rejected(&opened,"existing"),"file path")
  current := added(&opened,".")
  other := added(&opened,"other")
  require(current != other,"multiple watches")
  require(added(&opened,".") == current,"repeat add identity")
  stage("create")
  await_event(&opened,current,"café-😀",watch.Create,false)
  stage("write")
  await_event(&opened,current,"existing",watch.Modify,false)
  stage("rename")
  await_event(&opened,current,"renamed",watch.MoveTo,true)
  watch.acknowledge_rescan(&opened)
  require(!opened.rescan_required,"rescan acknowledgement")
  stage("delete")
  await_event(&opened,current,"renamed",watch.Delete,false)
  stage("other")
  await_event(&opened,other,"second",watch.Create,false)
  require(removed(&opened,current),"remove")
  require(!removed(&opened,current),"stale remove")
  stage("removed")
  await_event(&opened,other,"third",watch.Create,false)
  for attempt in 0..50 {
    result := watch.next(&status, &opened)
    require(!status.failed,"after remove")
    require(opened.ended || result.watch != current,"removed watch delivery")
    time.sleep(time.Millisecond*10)
  }
  stage("close")
  // Each close invalidates pending callbacks before freeing/reusing contexts.
  for iteration in 0..16 {
    pending := watch.open(&status, storage[..])
    require(!status.failed,"pending open")
    _ = added(&pending,".")
    time.sleep(time.Millisecond*5)
    watch.close(&pending)
    watch.close(&pending)
  }
  watch.close(&opened)
  stage("passed")
}
'''
# Compile this helper into a temporary copy of the real module. It exercises the
# actual private callback/queue without manufacturing filesystem overflow or
# exporting testing APIs. The nonzero stream value is compared, never called.
AUDIT = r'''
struct Next { event: Event, found: bool }
fn audit_next(watcher: *Watcher) Next {
  status: fail.Status
  item := next(&status, watcher)
  if status.failed { #panic("audit next") }
  return Next{ event: item, found: !watcher.ended }
}
fn audit_path(storage: []u8, text: []const u8) *const u8 {
  status: fail.Status
  path := c.string_into(&status, storage, text)
  if status.failed { #panic("audit path") }
  return path
}
pub fn audit_callbacks() {
  allocation := mem.arena_alloc(mem.ArenaHeader + #alignof(State) + #sizeof(State))
  defer { mem.arena_release(allocation) }
  state := mem.push<State>(allocation)
  slot := &state.slots[0]
  slot.owner = state
  slot.id = 7
  slot.mask = Changes
  slot.stream = #cast(rawptr, #cast(usize, 1))
  root := "/watched"
  slot.length = root.len
  for i in 0..root.len { slot.root[i] = root[i] }
  output: [1024]u8
  watcher := Watcher{state:state,storage:output[..]}
  name_storage: [128]u8
  pointers: [1]*const u8 = [audit_path(name_storage[..],"/watched/café-😀")]
  flags: [1]u32 = [256]
  ids: [1]u64 = [1]
  callback(nil,#cast(rawptr, slot),1,#cast(rawptr, &pointers[0]),&flags[0],&ids[0])
  item := audit_next(&watcher)
  if !item.found || item.event.watch != 7 || item.event.mask != Create || !bytes.equal(item.event.name,"café-😀") { #panic("callback Unicode child") }
  for i in 0..128 { name_storage[i] = 0 }
  if !bytes.equal(item.event.name,"café-😀") { #panic("callback retained borrowed native path") }
  pointers[0] = audit_path(name_storage[..],"/watched/nested/file")
  callback(nil,#cast(rawptr, slot),1,#cast(rawptr, &pointers[0]),&flags[0],&ids[0])
  if audit_next(&watcher).found { #panic("recursive event leaked") }
  pointers[0] = audit_path(name_storage[..],"/watched/file")
  flags[0] = 2048
  callback(nil,#cast(rawptr, slot),1,#cast(rawptr, &pointers[0]),&flags[0],&ids[0])
  item = audit_next(&watcher)
  if !item.event.rescan || item.event.cookie != 0 || item.event.mask != (MoveFrom|MoveTo) { #panic("callback rename") }
  flags[0] = 4
  callback(nil,#cast(rawptr, slot),1,#cast(rawptr, &pointers[0]),&flags[0],&ids[0])
  if !audit_next(&watcher).event.rescan || !watcher.rescan_required { #panic("kernel dropped events") }
  for audit_next(&watcher).found {}
  acknowledge_rescan(&watcher)
  for i in 0..80 { publish(slot,"overflow",Create,false) }
  if !audit_next(&watcher).event.rescan || !watcher.rescan_required { #panic("bounded queue overflow") }
  count: usize = 0
  for audit_next(&watcher).found { count += 1 }
  if count != 63 { #panic("queue capacity") }
  publish(slot,"reused",Create,false)
  if !bytes.equal(audit_next(&watcher).event.name,"reused") { #panic("queue wrap/reuse") }
  watcher.storage = output[..1]
  publish(slot,"long",Create,false)
  if !audit_next(&watcher).event.rescan { #panic("short caller output") }
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
