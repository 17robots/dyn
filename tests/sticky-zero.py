#!/usr/bin/env python3
"""Rules 6 and 7: writers keep their first error; zeroed values are valid and inert."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use mem "std/mem"
use "std/fail"
use fmt "std/fmt"
use builder "std/bytes/builder"
use process "std/process"
use io "std/io"
use watch "std/fs/watch"
fn check(ok: bool, message: []const u8) {
  if !ok {
    #panic(message)
  }
}
fn main() {
  storage: [4]u8
  out_status: fail.Status
  out := fmt.buffer(&out_status, storage[..])
  fmt.write(&out, "abc")
  fmt.write(&out, "toolong")
  fmt.write(&out, "d")
  check(out_status.failed && mem.equal(fmt.bytes(&out), "abc"), "fmt keeps the first failure")
  // clear empties the buffer; the failure stays on the status until reset.
  out_status = fail.Status{}
  fmt.clear(&out)
  fmt.write(&out, "ok")
  check(!out_status.failed, "fmt clear")
  fmt.clear(&out)
  fmt.write(&out, "abcd")
  fmt.write(&out, "")
  check(!out_status.failed, "fmt exact capacity and empty append")
  fmt.write(&out, "e")
  check(out_status.failed && mem.equal(fmt.bytes(&out), "abcd"), "fmt overflow preserves bytes")
  out_status = fail.Status{}
  fmt.clear(&out)
  fmt.write(&out, "ab")
  fmt.write(&out, storage[..2])
  check(!out_status.failed && mem.equal(fmt.bytes(&out), "abab"), "fmt append from own backing")
  bad_status: fail.Status
  bad := fmt.buffer(&bad_status, storage[..])
  bad.length = 5
  fmt.write(&bad, "")
  check(bad_status.failed && bad.length == 5, "fmt invalid cursor fails before slicing")
  bytes: [2]u8
  text := builder.from_buffer(bytes[..])
  appended: fail.Status
  builder.append(&appended, &text, "abc")
  builder.append(&appended, &text, "x")
  check(appended.failure.kind == fail.Kind.Capacity && builder.bytes(&text).len == 0, "status keeps the first failure")
  arena := mem.arena_alloc(0)
  builder.clear(&text)
  builder.append_grow(arena, &text, "grown")
  check(mem.equal(builder.bytes(&text), "grown"), "builder clear")
  arguments: [1][]const u8 = ["true"]
  spawned := process.spawn(arena, "/bin/true", arguments[..], process.Options{}) catch { #panic("zero options spawn") }
  exited := process.wait(spawned, false) catch { #panic("zero options wait") }
  check(exited.code == 0, "zero options inherit")
  idle: watch.Watcher
  watch.close(&idle)
  check(!idle.active, "zero watcher closes nothing")
}
'''
if not sys.platform.startswith('linux'):
    print('SKIP sticky and zero values: needs Linux for process and watch')
    sys.exit(0)
with tempfile.TemporaryDirectory(prefix='dyn-sticky-zero-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    output = project / 'program'
    for release in (False, True):
        subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--output', str(output),
                        *(['--release'] if release else [])], check=True, timeout=120)
        subprocess.run([str(output)], check=True, timeout=20)
print('PASS sticky errors in fmt and builder; zero process options and watcher (debug/release)')
