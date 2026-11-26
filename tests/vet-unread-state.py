#!/usr/bin/env python3
"""dyn vet, by shape: a struct local declared without a value and only ever
passed by pointer is never read (what the calls record in it is lost), or is
given a new value before what was recorded in it is read, and a
result tested for being empty before the state its call filled in is read.
No function or type is known by name."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/fail"
use "std/fs"
use "std/io"
use "std/mem"
use "std/process"

struct Counts { lines: u64 }
struct Note { failed: bool, count: u32 }

fn tally(counts: *Counts) {
  counts.lines += 1
}

fn record(note: *Note) {
  note.count += 1
}

fn main() {
  program := process.start()
  arena := program.arena
  lost: fail.Status
  save(&lost, "out.txt")
  status: fail.Status
  text := load(arena, &status, "in.txt", 1024)
  if status.failed { return }
  io.println("{}", text.len)
  other: fail.Status
  data := load(arena, &other, "in.txt", 1024)
  if data.len == 0 {
    io.println("missing")
  }
  _ = other
  third: fail.Status
  more := load(arena, &third, "in.txt", 1024)
  if third.failed { return }
  if more.len == 0 {
    io.println("empty file")
  }
  cleanup: fail.Status
  save(&cleanup, "out.txt")
  _ = cleanup
  file := fs.open("in.txt") catch { return }
  fs.close(&file)
  counts: Counts
  tally(&counts)
  io.println("{}", counts.lines)
  mine: Note
  record(&mine)
  reused: fail.Status
  save(&reused, "a.txt")
  reused = fail.Status{}
  save(&reused, "b.txt")
  if reused.failed { return }
  looked: fail.Status
  save(&looked, "c.txt")
  if looked.failed { io.println("c") }
  looked = fail.Status{}
  save(&looked, "d.txt")
  _ = looked
}

// Status-shaped helpers: the lint knows no function by name.
fn save(status: *fail.Status, path: []const u8) {
  if status.failed { return }
  fs.remove(path) catch err { fail.set(status, io.failure_of(err, "remove", path)) }
}

fn load(arena: *mem.Arena, status: *fail.Status, path: []const u8, maximum: usize) []u8 {
  empty: []u8
  if status.failed { return empty }
  data := fs.read_all(arena, path, maximum) catch err {
    fail.set(status, io.failure_of(err, "read", path))
    return empty
  }
  return data
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-vet-unread-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    env = dict(os.environ, DYN_SDK=str(ROOT))
    vetted = subprocess.run([DYN, 'vet', str(project)], capture_output=True, text=True, timeout=60, env=env)
    warnings = [line for line in vetted.stderr.splitlines() if 'warning:' in line]
    assert vetted.returncode == 1 and len(warnings) == 4, vetted.stderr
    def found(*parts):
        return any(all(part in line for part in parts) for line in warnings)
    assert found('main.dyn:21:3:', "'lost' is only ever passed by pointer and never read"), warnings
    assert found('main.dyn:29:6:', "an empty 'data' does not mean the call failed", "test 'other'"), warnings
    # A type of the user's own with the same shape is found the same way.
    assert found('main.dyn:47:3:', "'mine' is only ever passed by pointer"), warnings
    # A status given a new value before what was recorded in it is read; one
    # read in between, or none passed since, is fine.
    assert found('main.dyn:51:3:', "'reused' gets a new value before what the calls recorded in it is read"), warnings
    checked = subprocess.run([DYN, 'check', str(project)], capture_output=True, text=True, timeout=60, env=env)
    assert checked.returncode == 0, checked.stderr
print('PASS vet unread state: lost failures, statuses reset before they are read, and empty results as failure tests, by shape')
