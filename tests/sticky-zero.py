#!/usr/bin/env python3
"""Rules 6 and 7: writers keep their first error; zeroed values are valid and inert."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/mem" mem
use "std/fail"
use "std/fmt" fmt
use "std/bytes/builder" builder
use "std/process" process
use "std/io" io
use "std/fs/watch" watch
fn check(ok: bool, message: []const u8) {
  if !ok {
    #panic(message)
  }
}
fn main() {
  storage: [4]u8
  out := fmt.buffer(storage[..])
  fmt.write(&out, "abc")
  fmt.write(&out, "toolong")
  fmt.write(&out, "d")
  check(out.failed && mem.equal(fmt.bytes(&out), "abc"), "fmt keeps the first failure")
  fmt.clear(&out)
  fmt.write(&out, "ok")
  check(!out.failed, "fmt clear")
  fmt.clear(&out)
  fmt.write(&out, "abcd")
  fmt.write(&out, "")
  check(!out.failed, "fmt exact capacity and empty append")
  fmt.write(&out, "e")
  check(out.failed && mem.equal(fmt.bytes(&out), "abcd"), "fmt overflow preserves bytes")
  fmt.clear(&out)
  fmt.write(&out, "ab")
  fmt.write(&out, storage[..2])
  check(!out.failed && mem.equal(fmt.bytes(&out), "abab"), "fmt append from own backing")
  bad := fmt.buffer(storage[..])
  bad.length = 5
  fmt.write(&bad, "")
  check(bad.failed && bad.length == 5, "fmt invalid cursor fails before slicing")
  bytes: [2]u8
  text := builder.from_buffer(bytes[..])
  appended: fail.Status
  builder.append(&appended, &text, "abc")
  builder.append(&appended, &text, "x")
  check(appended.failure.kind == fail.Kind.Capacity && #len(builder.bytes(&text)) == 0, "status keeps the first failure")
  arena := mem.arena_alloc(0)
  builder.clear(&text)
  builder.append_grow(arena, &text, "grown")
  check(mem.equal(builder.bytes(&text), "grown"), "builder clear")
  arguments: [1][]const u8 = ["true"]
  status: fail.Status
  spawned := process.spawn(arena, &status, "/bin/true", arguments[..], process.Options{})
  check(!status.failed, "zero options spawn")
  exited := process.wait(&status, spawned, false)
  check(!status.failed && exited.code == 0, "zero options inherit")
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
