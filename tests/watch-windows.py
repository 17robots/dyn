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
SOURCE = r'''use watch "std/fs/watch"
use io "std/io"
use bytes "std/bytes"
use time "std/time"
fn require(value: bool) { if !value { #panic("Windows watch contract") } }
fn added(state: *watch.Watcher, path: []const u8, mask: u32) i32 {
  return watch.add(state, path, mask) catch { #panic("Windows watch contract") }
}
fn rejected(state: *watch.Watcher, path: []const u8, mask: u32) bool {
  _ = watch.add(state, path, mask) catch { return true }
  return false
}
fn removed(state: *watch.Watcher, id: i32) bool {
  watch.remove(state, id) catch { return false }
  return true
}
fn open_fails(storage: []u8) bool {
  failed := watch.open(storage) catch { return true }
  watch.close(&failed)
  return false
}
fn main() {
  empty := watch.Watcher{}
  watch.close(&empty)
  tiny: [1]u8
  require(open_fails(tiny[..]))
  scratch: [1024]u8
  opened := watch.open(scratch[..]) catch { #panic("Windows watch contract") }
  require(rejected(&opened,"missing-directory",watch.Changes))
  require(rejected(&opened,".",watch.CloseWrite))
  first := added(&opened,"one",watch.Changes)
  second := added(&opened,"two",watch.Changes)
  require(first != second)
  require(!watch.HasCloseWrite && !watch.HasMoveCookies && !watch.HasDirectoryFlag)
  capacity_scratch: [272]u8
  capacity := watch.open(capacity_scratch[..]) catch { #panic("Windows watch contract") }
  ids: [16]i32
  for i in 0..16 {
    ids[i] = added(&capacity,".",watch.Changes)
  }
  require(rejected(&capacity,".",watch.Changes))
  require(removed(&capacity,ids[0]))
  replacement := added(&capacity,".",watch.Changes)
  require(replacement != ids[0])
  require(!removed(&capacity,ids[0]))
  // Closing all remaining idle watches must cancel pending native requests.
  watch.close(&capacity)
  watch.close(&capacity)
  io.println("READY")
  seen_first: u32 = 0
  seen_second: u32 = 0
  for attempt in 0..1000 {
    event := watch.next(&opened) catch { #panic("Windows watch contract") }
    if !opened.ended {
      require(!event.rescan && event.cookie == 0)
      if event.watch == first {
        if bytes.equal(event.name,"café-😀.txt") {
          seen_first = seen_first | (event.mask & (watch.Create | watch.MoveFrom))
        }
        if bytes.equal(event.name,"renamé-😀.txt") {
          seen_first = seen_first | (event.mask & (watch.MoveTo | watch.Delete))
        }
      }
      if event.watch == second && bytes.equal(event.name,"二.txt") {
        seen_second = seen_second | (event.mask & (watch.Create | watch.Delete))
      }
    }
    if seen_first == (watch.Create | watch.MoveFrom | watch.MoveTo | watch.Delete) && seen_second == (watch.Create | watch.Delete) { break }
    if opened.ended { time.sleep(10000000) }
  }
  require(seen_first == (watch.Create | watch.MoveFrom | watch.MoveTo | watch.Delete))
  require(seen_second == (watch.Create | watch.Delete))
  require(removed(&opened,first))
  require(removed(&opened,second))
  watch.close(&opened)
  reopened := watch.open(scratch[..]) catch { #panic("Windows watch contract") }
  _ = added(&reopened,"one",watch.Changes)
  watch.close(&reopened)
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
