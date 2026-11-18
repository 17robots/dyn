#!/usr/bin/env python3
"""A failure's text lives in a ring the process shares: a Status is 64 bytes,
a failure keeps up to 1 KiB of text with a long path keeping its end, the
text survives other failures for a while, and once newer text has taken its
place describe gives the kind and the system's code. Threads recording at
once keep their own text."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/fail"
use "std/io"
use "std/fs"
use "std/mem"
use "std/thread"
use "std/bytes"
fn check(ok: bool, message: []const u8) { if !ok { #panic(message) } }
struct Work { index: u8, good: bool }
fn worker(work: *Work) isize {
  name: [1]u8 = [work.index]
  work.good = true
  for i in 0..20000 {
    status: fail.Status
    fail.invalid(&status, "check", name[..], "worker message")
    if !bytes.equal(fail.path_text(&status.failure), name[..]) || !bytes.equal(fail.message_text(&status.failure), "worker message") {
      work.good = false
    }
  }
  return 0
}
fn main() {
  check(#sizeof(fail.Failure) == 40 && #sizeof(fail.Status) == 64, "sizes")
  storage: [2048]u8
  status: fail.Status
  _ = fs.open(&status, "/nonexistent/dir/file.txt")
  io.println("{}", fail.describe(storage[..], status.failure))
  kept := status.failure
  for i in 0..10 {
    other: fail.Status
    fail.invalid(&other, "check", "a/path", "a short message")
  }
  io.println("{}", fail.describe(storage[..], kept))
  // The ring shard comes from the stack address: fill through the same call
  // as the kept failure, so its text lands in the same shard wherever the
  // stack is.
  for i in 0..2000 {
    other: fail.Status
    _ = fs.open(&other, "/nonexistent/dir/file.txt")
  }
  io.println("{}", fail.describe(storage[..], kept))
  check(#len(fail.path_text(&kept)) == 0, "lost text is empty")
  long: [3000]u8
  for i in 0..3000 {
    long[i] = 'a' + #cast(u8, i % 26)
  }
  big: fail.Status
  fail.invalid(&big, "read", long[..], "too long")
  path := fail.path_text(&big.failure)
  check(#len(path) == 1024 - 4 - 8 && bytes.equal(path[..3], "...") && bytes.equal(path[#len(path) - 4..], long[2996..]), "long path keeps its end")
  bare: fail.Status
  fail.at(&bare, fail.Kind.InvalidInput, "", "", 7)
  io.println("{}", fail.describe(storage[..], bare.failure))
  arena := mem.arena_alloc(0)
  defer mem.arena_release(arena)
  stacks: [4][65536]u8
  works: [4]Work
  handles: [4]*thread.Thread
  spawning := fail.Status{ on_failure: fail.panic_on_failure }
  for i in 0..4 {
    works[i] = Work{ index: 'A' + #cast(u8, i) }
    handles[i] = thread.spawn(arena, &spawning, stacks[i][..], worker, &works[i])
  }
  for i in 0..4 {
    thread.join(&spawning, handles[i])
    check(works[i].good, "thread text")
  }
}
'''
EXPECTED = '''open /nonexistent/dir/file.txt: no such file or directory
open /nonexistent/dir/file.txt: no such file or directory
not found (code -2)
at 7: invalid input
'''
with tempfile.TemporaryDirectory(prefix='dyn-failure-text-') as temporary:
    project = Path(temporary) / 'text'
    project.mkdir()
    (project / 'main.dyn').write_text(SOURCE)
    for mode in ('--debug', '--release'):
        program = project / 'program'
        subprocess.run([DYN, 'build', str(project), mode, '--quiet', '--no-cache', '--output', str(program)],
                       check=True, timeout=180)
        result = subprocess.run([str(program)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0 and result.stdout == EXPECTED, (mode, result.returncode, result.stdout, result.stderr)
print('PASS failure text: 64-byte Status, 1 KiB text, long paths keep their end, lost text falls back, threads keep theirs')
