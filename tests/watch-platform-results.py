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
 body={'native_error':'return mock_code','reset_event':'mock_resets += 1 return mock_reset','read_changes':'mock_reads += 1 return mock_read','native_open':'return #cast(rawptr, 1)','create_event':'return #cast(rawptr, 2)','native_close':'return 1','completion':'return 0','cancel':'return 1'}[name]
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
 require(failure(-5).kind == errors.Kind.PermissionDenied)
 require(validation_failure(-95).kind == errors.Kind.Unsupported)
 closed := Watcher{}
 require(next(&closed).kind == errors.Kind.InvalidState)
 backing: [272]u8 = []
 opened := open(backing[..])
 state := opened.value
 added := add(&state, "test", Create)
 require(!added.ok && added.error == 0 && added.kind == errors.Kind.System)
 require(mock_resets == 1 && mock_reads == 0)
 mock_reset = 1
 added = add(&state, "test", Create)
 require(!added.ok && added.error == 0 && added.kind == errors.Kind.System)
 require(mock_reads == 1)
 slot := &state.native.slots[0]
 slot.id = 1
 slot.handle = #cast(rawptr, 1)
 slot.event = #cast(rawptr, 2)
 first := next(&state)
 require(first.status == Status.Error && first.error == 0 && first.kind == errors.Kind.System)
 reads := mock_reads
 mock_code = 5
 repeated := next(&state)
 require(repeated.error == 0 && repeated.kind == errors.Kind.System && mock_reads == reads)
 require(close(&state).ok)
 require(next(&state).error == 0)
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
fn canonical_mock(path: *const u8, output: *u8) *u8 { _ = path _ = output return nil }
fn require(ok: bool) { if !ok { #panic("macos mock") } }
fn main() {
 backing: [272]u8 = []
 opened := open(backing[..])
 require(!opened.ok && opened.error == -95 && opened.kind == errors.Kind.Unsupported)
 state := State{api: API{canonical: &canonical_mock}}
 watcher := Watcher{state: &state}
 unsupported := add(&watcher, "test", CloseWrite)
 require(!unsupported.ok && unsupported.error == -95 && unsupported.kind == errors.Kind.Unsupported)
 denied := add(&watcher, "test", Create)
 require(!denied.ok && denied.error == -13 && denied.kind == errors.Kind.PermissionDenied)
 mock_errno = 63
 long := add(&watcher, "test", Create)
 require(!long.ok && long.error == -63 && long.kind == errors.Kind.InvalidInput)
}
'''
run('macos',s)
