#!/usr/bin/env python3
"""dyn vet, by shape: a struct local declared without a value and only ever
passed by pointer is never read (what the calls record in it is lost), and a
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
  fs.write_all(&lost, "out.txt", "x")
  status: fail.Status
  text := fs.read_all(arena, &status, "in.txt", 1024)
  if status.failed { return }
  io.println("{}", #len(text))
  other: fail.Status
  data := fs.read_all(arena, &other, "in.txt", 1024)
  if #len(data) == 0 {
    io.println("missing")
  }
  _ = other
  third: fail.Status
  more := fs.read_all(arena, &third, "in.txt", 1024)
  if third.failed { return }
  if #len(more) == 0 {
    io.println("empty file")
  }
  cleanup: fail.Status
  fs.remove(&cleanup, "out.txt")
  _ = cleanup
  file := fs.open(&status, "in.txt")
  fs.close(&file)
  counts: Counts
  tally(&counts)
  io.println("{}", counts.lines)
  mine: Note
  record(&mine)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-vet-unread-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    env = dict(os.environ, DYN_SDK=str(ROOT))
    vetted = subprocess.run([DYN, 'vet', str(project)], capture_output=True, text=True, timeout=60, env=env)
    warnings = [line for line in vetted.stderr.splitlines() if 'warning:' in line]
    assert vetted.returncode == 1 and len(warnings) == 3, vetted.stderr
    def found(*parts):
        return any(all(part in line for part in parts) for line in warnings)
    assert found('main.dyn:20:3:', "'lost' is only ever passed by pointer and never read"), warnings
    assert found('main.dyn:28:6:', "an empty 'data' does not mean the call failed", "test 'other'"), warnings
    # A type of the user's own with the same shape is found the same way.
    assert found('main.dyn:46:3:', "'mine' is only ever passed by pointer"), warnings
    checked = subprocess.run([DYN, 'check', str(project)], capture_output=True, text=True, timeout=60, env=env)
    assert checked.returncode == 0, checked.stderr
print('PASS vet unread state: lost failures and empty results as failure tests, by shape')
