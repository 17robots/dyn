#!/usr/bin/env python3
"""Execute Darwin CString setup with bounded host mocks; cross-check both ABIs."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
macos = (ROOT / 'std/process/macos.dyn').read_text()
process = (ROOT / 'std/process/process.dyn').read_text()
# Compile the production conversion/setup bodies, replacing only OS entry points.
adapter = ('use "std/mem" mem\nuse "std/c" c\nuse "std/bytes" bytes\n'
           'use "std/errors" error_kinds\n'
           + process[process.index('pub struct Redirect'):process.index('pub struct ExitResult')]
           + macos[macos.index('struct CString'):macos.index('fn wait_native')])
MOCKS = '''
fn native_errno() *i32 { #panic("unexpected errno") }
fn native_fcntl(descriptor: i32, command: i32, minimum: i32) i32 { return descriptor + 10 }
fn native_close(descriptor: i32) i32 { return 0 }
fn native_pipe(descriptors: *i32) i32 {
  descriptors[..2][0] = 3
  descriptors[..2][1] = 4
  return 0
}
fn native_fork() i32 { return 42 }
fn native_dup(source: i32, destination: i32) i32 { return 0 }
fn native_chdir(path: *const u8) i32 { return 0 }
fn native_exec(path: *const u8, arguments: rawptr, environment: rawptr) i32 { return 0 }
fn native_write(descriptor: i32, source: rawptr, count: usize) isize { return 0 }
fn native_exit(code: i32) { #panic("unexpected child") }
fn native_read(descriptor: i32, destination: *u8, count: usize) isize { return 0 }
fn native_kill(child: i32, signal: i32) i32 { return 0 }
fn native_wait(child: i32, status: *i32, flags: i32) i32 { return 0 }
fn main() {
  storage: [4096]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  mark := mem.arena_mark(arena)
  empty := c_string(arena, "")
  if empty == nil || empty.* != 0 || mem.arena_mark(arena) != mark + 1 {
    #panic("empty CString allocation")
  }
  text := c_string(arena, "café-😀")
  parsed := c.bytes_from_string(text, 16)
  if !parsed.ok || !bytes.equal(parsed.value, "café-😀") { #panic("CString bytes") }
  before_invalid := mem.arena_mark(arena)
  invalid: [3]u8 = ['a', 0, 'b']
  if c_string(arena, invalid[..]) != nil || mem.arena_mark(arena) != before_invalid {
    #panic("interior NUL rollback")
  }
  arguments: [3][]const u8 = ["program", "", "café-😀"]
  vector := c_vector(arena, arguments[..])
  if vector == nil || vector[..4][3].value != nil { #panic("vector sentinel") }
  for at in 0..3 {
    item := c.bytes_from_string(vector[..4][at].value, 32)
    if !item.ok || !bytes.equal(item.value, arguments[at]) { #panic("vector bytes") }
  }
  before_spawn := mem.arena_mark(arena)
  environment: [1][]const u8 = ["KEY=value"]
  result := spawn_native(arena, "/program", arguments[..], Options{environment: environment[..], directory: "/tmp"})
  if !result.ok || result.value.handle != 42 || mem.arena_mark(arena) != before_spawn {
    #panic("spawn setup and rewind")
  }
  rejected := spawn_native(arena, invalid[..], arguments[..], Options{})
  if rejected.ok || mem.arena_mark(arena) != before_spawn { #panic("failed setup rewind") }
  if !bytes.equal(c.bytes_from_string(text, 16).value, "café-😀") { #panic("live allocation") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-process-cstring-') as temporary:
    root = Path(temporary)
    host = root / 'host'
    host.mkdir()
    (host / 'main.dyn').write_text(adapter + MOCKS)
    for mode in ('--debug', '--release'):
        output = root / mode[2:]
        subprocess.run([DYN, 'build', str(host), mode, '--no-cache', '--quiet', '--jobs', '1', '--output', str(output)], cwd=ROOT, check=True, timeout=90)
        subprocess.run([str(output)], check=True, timeout=10)
    native = root / 'native'
    native.mkdir()
    (native / 'main.dyn').write_text('''use "std/process"
use "std/mem"
fn main() {
  storage: [4096]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  arguments: [1][]const u8 = ["/usr/bin/true"]
  _ = process.spawn(arena, arguments[0], arguments[..], process.Options{})
}
''')
    for target in ('x86_64-macos', 'aarch64-macos'):
        subprocess.run([DYN, 'build', str(native), '--target', target, '--no-link', '--no-cache', '--quiet', '--jobs', '1', '--output', str(root / target)], cwd=ROOT, check=True, timeout=90)
print('PASS Darwin CString bytes, vectors, validation, rewind; host debug/release and Darwin x64/arm64')
