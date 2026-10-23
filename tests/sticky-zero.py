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
use "std/fmt" fmt
use "std/bytes/builder" builder
use "std/process" process
use "std/fs/watch" watch
use "std/strings" strings
fn check(ok: bool, message: []const u8) {
  if !ok {
    #panic(message)
  }
}
fn main() {
  storage: [4]u8 = []
  out := fmt.buffer(storage[..])
  _ = fmt.write(&out, "abc")
  _ = fmt.write(&out, "toolong")
  check(out.failed && !fmt.write(&out, "d") && strings.equal(fmt.bytes(&out), "abc"), "fmt keeps the first failure")
  fmt.clear(&out)
  check(!out.failed && fmt.write(&out, "ok"), "fmt clear")
  bytes: [2]u8 = []
  text := builder.from_buffer(bytes[..])
  _ = builder.append(&text, "abc")
  arena: mem.Arena
  check(text.error == builder.ErrorKind.Capacity && builder.append_grow(&text, &arena, "x") == builder.ErrorKind.Capacity, "builder keeps the first failure")
  builder.clear(&text)
  check(text.error == builder.ErrorKind.None && builder.append_grow(&text, &arena, "grown") == builder.ErrorKind.None, "builder clear")
  arguments: [1][]const u8 = ["true"]
  spawned := process.spawn(&arena, "/bin/true", arguments[..], process.Options{})
  check(spawned.ok, "zero options spawn")
  exited := process.wait(&spawned.value, false)
  check(exited.ok && exited.code == 0, "zero options inherit")
  idle: watch.Watcher
  check(watch.close(&idle).ok && !idle.active, "zero watcher closes nothing")
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
