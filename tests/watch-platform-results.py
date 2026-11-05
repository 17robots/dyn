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
 require(failure(-5).failure.kind == errors.Kind.PermissionDenied)
 require(validation_failure(-95).failure.kind == errors.Kind.Unsupported)
 closed := Watcher{}
 require(next(&closed).failure.kind == errors.Kind.InvalidState)
 backing: [272]u8 = []
 opened := open(backing[..])
 state := opened.value
 added := add(&state, "test", Create)
 require(added.failure.kind != errors.Kind.Ok && added.failure.native == 0 && added.failure.kind == errors.Kind.System)
 require(mock_resets == 1 && mock_reads == 0)
 mock_reset = 1
 added = add(&state, "test", Create)
 require(added.failure.kind != errors.Kind.Ok && added.failure.native == 0 && added.failure.kind == errors.Kind.System)
 require(mock_reads == 1)
 slot := &state.native.slots[0]
 slot.id = 1
 slot.handle = #cast(rawptr, 1)
 slot.event = #cast(rawptr, 2)
 first := next(&state)
 require(first.status == Status.Error && first.failure.native == 0 && first.failure.kind == errors.Kind.System)
 reads := mock_reads
 mock_code = 5
 repeated := next(&state)
 require(repeated.failure.native == 0 && repeated.failure.kind == errors.Kind.System && mock_reads == reads)
 require(close(&state).failure.kind == errors.Kind.Ok)
 require(next(&state).failure.native == 0)
}
'''
run('windows',s)
s=(root/'std/fs/watch/macos.dyn').read_text().replace('#target(kernel: darwin)','')
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
 owner := mem.arena_create(0)
 live := Watcher{arena: owner, state: mem.push(State, owner)}
 require(close(&live).failure.kind == errors.Kind.Ok)
 require(live.arena == nil && live.state == nil)
 require(close(&live).failure.kind == errors.Kind.Ok)
 partial := Watcher{arena: mem.arena_create(0)}
 require(close(&partial).failure.kind == errors.Kind.Ok && partial.arena == nil)
 require(close(&partial).failure.kind == errors.Kind.Ok)
 empty := Watcher{}
 require(close(&empty).failure.kind == errors.Kind.Ok && close(&empty).failure.kind == errors.Kind.Ok)
 backing: [272]u8 = []
 opened := open(backing[..])
 require(opened.failure.kind != errors.Kind.Ok && opened.failure.native == -95 && opened.failure.kind == errors.Kind.Unsupported)
 state := State{api: API{canonical: canonical_mock}}
 watcher := Watcher{state: &state}
 unsupported := add(&watcher, "test", CloseWrite)
 require(unsupported.failure.kind != errors.Kind.Ok && unsupported.failure.native == -95 && unsupported.failure.kind == errors.Kind.Unsupported)
 denied := add(&watcher, "test", Create)
 require(denied.failure.kind != errors.Kind.Ok && denied.failure.native == -13 && denied.failure.kind == errors.Kind.PermissionDenied)
 mock_errno = 63
 long := add(&watcher, "test", Create)
 require(long.failure.kind != errors.Kind.Ok && long.failure.native == -63 && long.failure.kind == errors.Kind.InvalidInput)
}
'''
run('macos',s)
