#!/usr/bin/env python3
"""Windows asynchronous directory watch ownership and real event contracts."""
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build' / ('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve()
SOURCE = r'''use "std/fs/watch" watch
use "std/io" io
use "std/bytes" bytes
use "std/time" time
fn require(value: bool) { if !value { #panic("Windows watch contract") } }
fn main() {
  empty := watch.Watcher{}
  watch.close(&empty)
  tiny: [1]u8
  failed := watch.open(tiny[..])
  watch.close(&failed.value)
  require(io.failed(failed.failure))
  scratch: [1024]u8
  opened := watch.open(scratch[..])
  require(!io.failed(opened.failure))
  require(io.failed(watch.add(&opened.value,"missing-directory",watch.Changes).failure))
  require(io.failed(watch.add(&opened.value,".",watch.CloseWrite).failure))
  first := watch.add(&opened.value,"one",watch.Changes)
  second := watch.add(&opened.value,"two",watch.Changes)
  require(!io.failed(first.failure) && !io.failed(second.failure) && first.value != second.value)
  require(!watch.HasCloseWrite && !watch.HasMoveCookies && !watch.HasDirectoryFlag)
  capacity_scratch: [272]u8
  capacity := watch.open(capacity_scratch[..])
  require(!io.failed(capacity.failure))
  ids: [16]i32
  for i in 0..16 {
    added := watch.add(&capacity.value,".",watch.Changes)
    require(!io.failed(added.failure))
    ids[i] = added.value
  }
  require(io.failed(watch.add(&capacity.value,".",watch.Changes).failure))
  require(!io.failed(watch.remove(&capacity.value,ids[0]).failure))
  replacement := watch.add(&capacity.value,".",watch.Changes)
  require(!io.failed(replacement.failure) && replacement.value != ids[0])
  require(io.failed(watch.remove(&capacity.value,ids[0]).failure))
  // Closing all remaining idle watches must cancel pending native requests.
  watch.close(&capacity.value)
  watch.close(&capacity.value)
  io.println("READY")
  seen_first: u32 = 0
  seen_second: u32 = 0
  for attempt in 0..1000 {
    event := watch.next(&opened.value)
    require(!io.failed(event.failure))
    if event.status == watch.Status.Event {
      require(!event.event.rescan && event.event.cookie == 0)
      if event.event.watch == first.value {
        if bytes.equal(event.event.name,"café-😀.txt") {
          seen_first = seen_first | (event.event.mask & (watch.Create | watch.MoveFrom))
        }
        if bytes.equal(event.event.name,"renamé-😀.txt") {
          seen_first = seen_first | (event.event.mask & (watch.MoveTo | watch.Delete))
        }
      }
      if event.event.watch == second.value && bytes.equal(event.event.name,"二.txt") {
        seen_second = seen_second | (event.event.mask & (watch.Create | watch.Delete))
      }
    }
    if seen_first == (watch.Create | watch.MoveFrom | watch.MoveTo | watch.Delete) && seen_second == (watch.Create | watch.Delete) { break }
    if event.status == watch.Status.Empty { require(!io.failed(time.sleep(10000000).failure)) }
  }
  require(seen_first == (watch.Create | watch.MoveFrom | watch.MoveTo | watch.Delete))
  require(seen_second == (watch.Create | watch.Delete))
  require(!io.failed(watch.remove(&opened.value,first.value).failure))
  require(!io.failed(watch.remove(&opened.value,second.value).failure))
  watch.close(&opened.value)
  reopened := watch.open(scratch[..])
  require(!io.failed(reopened.failure) && !io.failed(watch.add(&reopened.value,"one",watch.Changes).failure))
  watch.close(&reopened.value)
  io.println("DONE")
}
'''

def execute(output, directory):
    process = subprocess.Popen([str(output)], cwd=directory, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding='utf-8')
    lines = queue.Queue()
    def read_lines():
        for line in process.stdout:
            lines.put(line.strip())
        lines.put(None)
    reader = threading.Thread(target=read_lines, daemon=True)
    reader.start()
    transcript = []
    try:
        line = lines.get(timeout=20)
        transcript.append(line)
        assert line == 'READY', transcript
        first = directory / 'one' / 'café-😀.txt'
        first.write_text('payload', encoding='utf-8')
        renamed = first.with_name('renamé-😀.txt')
        first.rename(renamed)
        renamed.unlink()
        second = directory / 'two' / '二.txt'
        second.write_text('payload', encoding='utf-8')
        second.unlink()
        while True:
            line = lines.get(timeout=20)
            if line is None:
                break
            transcript.append(line)
        assert process.wait(timeout=5) == 0 and 'DONE' in transcript, transcript
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        reader.join(timeout=5)
        process.stdout.close()

with tempfile.TemporaryDirectory(prefix='dyn-watch-windows-') as temporary:
    root = Path(temporary)
    source = root / 'source'
    source.mkdir()
    (source / 'main.dyn').write_text(SOURCE, encoding='utf-8')
    for mode in ('--debug', '--release'):
        output = root / 'watch.exe'
        subprocess.run([str(DYN), 'build', str(source), '--target', 'x86_64-windows', mode,
                        '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=90)
        if os.name == 'nt':
            directory = root / mode
            (directory / 'one').mkdir(parents=True)
            (directory / 'two').mkdir()
            execute(output, directory)
if os.name == 'nt':
    print('PASS Windows Unicode create/rename/delete, multiple watches, capacity, cancellation, and reopen (debug/release)')
else:
    print('PASS Windows watch cross-build/link (debug/release); native execution not covered on this host')
