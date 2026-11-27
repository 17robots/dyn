#!/usr/bin/env python3
"""Execute watcher platform logic with injected native calls on Linux.

These are deterministic fault-injection tests, not Windows/macOS execution.
The production module is copied and native extern declarations replaced with
counting substitutes. No retained temporary fixture is required.
"""
from pathlib import Path
import tempfile, subprocess, os, re
root=Path(__file__).resolve().parents[1]
dyn=str(Path(os.environ.get('DYN',root/'build/dyn-release')).resolve())
env=dict(os.environ,DYN_SDK=str(root))
def run(name,s):
 with tempfile.TemporaryDirectory(prefix='watch-'+name) as t:
  p=Path(t); (p/'main.dyn').write_text(s)
  for mode in ('debug','release'):
   subprocess.run([dyn,'build',t,'--quiet','--no-cache','--'+mode,'--output',str(p/'probe')],env=env,check=True,timeout=120)
   subprocess.run([str(p/'probe')],check=True,timeout=10)
   print('PASS',name,mode)
s=(root/'std/fs/watch/windows.dyn').read_text().replace('#target(kernel: windows)','')
def win(m):
 line=m[0]; name=re.search(r'fn (\w+)',line)[1]; sig=re.sub(r' "[^"]+"','',line.removeprefix('extern '))
 body={'native_error':'return mock_code','reset_event':'mock_resets += 1\nreturn mock_reset','read_changes':'mock_reads += 1\nreturn mock_read','native_open':'return #cast(rawptr, 1)','create_event':'return #cast(rawptr, 2)','native_close':'return 1','completion':'return 0','cancel':'return 1'}[name]
 return sig+' { '+body+' }'
s=re.sub(r'^extern fn .+$',win,s,flags=re.M)
s+='''
mock_code: u32 = 0
mock_reset: i32 = 0
mock_read: i32 = 0
mock_resets: i32 = 0
mock_reads: i32 = 0
fn require(ok: bool) { if !ok { #panic("windows mock") } }
fn main() {
 require(tag(io.windows_err(-5)) == -1001)
 require(tag(io.linux_err(-95)) == -1002)
 closed := Watcher{}
 require(next_failure(&closed) == -1003)
 backing: [272]u8
 state := open(backing[..]) catch { #panic("open") }
 require(add_failure(&state, "test", Create) == 0)
 require(mock_resets == 1 && mock_reads == 0)
 mock_reset = 1
 require(add_failure(&state, "test", Create) == 0)
 require(mock_reads == 1)
 slot := &state.native.slots[0]
 slot.id = 1
 slot.handle = #cast(rawptr, 1)
 slot.event = #cast(rawptr, 2)
 require(next_failure(&state) == 0)
 reads := mock_reads
 mock_code = 5
 require(next_failure(&state) == 0 && mock_reads == reads)
 close(&state)
 require(next_failure(&state) == 0)
}
// The system code for System; -1001 PermissionDenied, -1002 Unsupported,
// -1003 InvalidInput, -1004 anything else.
fn tag(err: io.IoErr) isize {
 case err {
  .System(native) => { return native }
  .PermissionDenied => { return -1001 }
  .Unsupported => { return -1002 }
  .InvalidInput => { return -1003 }
  _ => { return -1004 }
 }
}
fn next_failure(state: *Watcher) isize {
 _ = next(state) catch err { return tag(err) }
 #panic("next succeeded")
}
fn add_failure(state: *Watcher, path: []const u8, mask: u32) isize {
 _ = add(state, path, mask) catch err { return tag(err) }
 #panic("add succeeded")
}
'''
run('windows',s)
s=(root/'std/fs/watch/macos.dyn').read_text().replace('#target(kernel: darwin)','')
# std/os/macos/sys is darwin-only: inline the numbers it names.
numbers=dict(re.findall(r'pub const (\w+): u64 = (\d+)',(root/'std/os/macos/sys/sys.dyn').read_text()))
s=re.sub(r'sys\.(\w+)',lambda m:numbers[m[1]],s.replace('use "std/os/macos/sys"\n',''))
def mac(m):
 line=m[0]; name=re.search(r'fn (\w+)',line)[1]; sig=re.sub(r' "[^"]+"','',line.removeprefix('extern '))
 body=''
 if name=='native_errno': body='return &mock_errno'
 elif line.endswith(' rawptr'): body='return nil'
 elif line.endswith(' i32'): body='return 0'
 return sig+' { '+body+' }'
s=re.sub(r'^extern fn .+$',mac,s,flags=re.M)
s+='''
mock_errno: i32 = 13
fn canonical_mock(path: *const u8, output: *u8) *u8 { _ = path
_ = output
return nil }
fn require(ok: bool) { if !ok { #panic("macos mock") } }
fn main() {
 owner := mem.arena_alloc(0)
 live := Watcher{arena: owner, state: mem.push<State>(owner)}
 close(&live)
 require(live.arena == nil && live.state == nil)
 close(&live)
 partial := Watcher{arena: mem.arena_alloc(0)}
 close(&partial)
 require(partial.arena == nil)
 close(&partial)
 empty := Watcher{}
 close(&empty)
 close(&empty)
 backing: [272]u8
 _ = open(backing[..]) catch err {
  require(tag(err) == -1002)
  check_add()
  return
 }
 #panic("open succeeded")
}
fn check_add() {
 state := State{api: API{canonical: canonical_mock}}
 watcher := Watcher{state: &state}
 require(add_failure(&watcher, "test", CloseWrite) == -1002)
 require(add_failure(&watcher, "test", Create) == -1001)
 mock_errno = 63
 require(add_failure(&watcher, "test", Create) == -1003)
}
// The system code for System; -1001 PermissionDenied, -1002 Unsupported,
// -1003 InvalidInput, -1004 anything else.
fn tag(err: io.IoErr) isize {
 case err {
  .System(native) => { return native }
  .PermissionDenied => { return -1001 }
  .Unsupported => { return -1002 }
  .InvalidInput => { return -1003 }
  _ => { return -1004 }
 }
}
fn add_failure(watcher: *Watcher, path: []const u8, mask: u32) isize {
 _ = add(watcher, path, mask) catch err { return tag(err) }
 #panic("add succeeded")
}
'''
run('macos',s)
