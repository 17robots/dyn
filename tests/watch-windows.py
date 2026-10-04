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
  require(watch.close(&empty).ok)
  tiny: [1]u8 = []
  failed := watch.open(tiny[..])
  require(!failed.ok && watch.close(&failed.watcher).ok)
  scratch: [1024]u8 = []
  opened := watch.open(scratch[..])
  require(opened.ok)
  require(!watch.add(&opened.watcher,"missing-directory",watch.Changes).ok)
  require(!watch.add(&opened.watcher,".",watch.CloseWrite).ok)
  first := watch.add(&opened.watcher,"one",watch.Changes)
  second := watch.add(&opened.watcher,"two",watch.Changes)
  require(first.ok && second.ok && first.value != second.value)
  require(!watch.HasCloseWrite && !watch.HasMoveCookies && !watch.HasDirectoryFlag)
  capacity_scratch: [272]u8 = []
  capacity := watch.open(capacity_scratch[..])
  require(capacity.ok)
  ids: [16]i32 = []
  for i in 0..16 {
    added := watch.add(&capacity.watcher,".",watch.Changes)
    require(added.ok)
    ids[i] = added.value
  }
  require(!watch.add(&capacity.watcher,".",watch.Changes).ok)
  require(watch.remove(&capacity.watcher,ids[0]).ok)
  replacement := watch.add(&capacity.watcher,".",watch.Changes)
  require(replacement.ok && replacement.value != ids[0])
  require(!watch.remove(&capacity.watcher,ids[0]).ok)
  // Closing all remaining idle watches must cancel pending native requests.
  require(watch.close(&capacity.watcher).ok && watch.close(&capacity.watcher).ok)
  _ = io.println(io.stdout(),"READY")
  seen_first: u32 = 0
  seen_second: u32 = 0
  for attempt in 0..1000 {
    event := watch.next(&opened.watcher)
    require(event.status != watch.Status.Error)
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
    if event.status == watch.Status.Empty { require(time.sleep(10000000)) }
  }
  require(seen_first == (watch.Create | watch.MoveFrom | watch.MoveTo | watch.Delete))
  require(seen_second == (watch.Create | watch.Delete))
  require(watch.remove(&opened.watcher,first.value).ok)
  require(watch.remove(&opened.watcher,second.value).ok)
  require(watch.close(&opened.watcher).ok)
  reopened := watch.open(scratch[..])
  require(reopened.ok && watch.add(&reopened.watcher,"one",watch.Changes).ok)
  require(watch.close(&reopened.watcher).ok)
  _ = io.println(io.stdout(),"DONE")
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
