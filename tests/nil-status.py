#!/usr/bin/env python3
"""A nil status means the caller does not care why a call fails: every
public std function takes it, records nothing, and returns its usual zero
value. Inside, the call still sees its own failures, so a reader still ends
and a writer that ran out of room stops instead of leaving a gap."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/bufio"
use "std/bytes"
use "std/encoding/json"
use "std/fail"
use "std/fmt"
use "std/fs"
use "std/html"
use "std/io"
use "std/mem"
use "std/process"

fn check(ok: bool, message: []const u8) {
  if !ok { #panic(message) }
}

fn main() {
  arena := mem.arena_alloc(mem.MiB)
  defer mem.arena_release(arena)
  // Failures are dropped; the value is the usual zero.
  check(fs.read_all(arena, nil, "/no/such/file", 1024).len == 0, "read_all")
  check(process.environment(arena, nil, "DYN_NIL_STATUS_UNSET").len == 0, "environment")
  fail.invalid(nil, "check", "", "dropped")
  root := json.parse(arena, nil, "{\"port\": 8080}")
  check(json.get<i64>(nil, root, "port") == 8080, "json present")
  check(json.get<i64>(nil, root, "missing") == 0, "json missing")
  // A reader on a file that is not there ends at once.
  file := fs.open(nil, "/no/such/file")
  storage: [64]u8
  reader := bufio.reader(fs.reader(&file), storage[..])
  lines: usize = 0
  for {
    _ = bufio.read_line(nil, &reader)
    if reader.ended { break }
    lines += 1
  }
  check(lines == 0, "reader")
  // A full writer stops: no later write lands after a gap.
  small: [8]u8
  out := fmt.buffer(nil, small[..])
  fmt.write(&out, "12345")
  fmt.write(&out, "6789")
  fmt.write(&out, "x")
  check(bytes.equal(fmt.bytes(&out), "12345"), "buffer stops")
  fmt.clear(&out)
  fmt.write(&out, "ok")
  check(bytes.equal(fmt.bytes(&out), "ok"), "buffer clear")
  page_storage: [64]u8
  page := html.writer(nil, page_storage[..])
  html.print(&page, "<p>{}</p>", "a & b")
  check(bytes.equal(html.output(&page).bytes, "<p>a &amp; b</p>"), "html")
  json_storage: [64]u8
  doc := json.writer(nil, json_storage[..])
  json.key(&doc, "outside")
  json.object_begin(&doc)
  check(json.output(&doc).len == 0, "json writer stops after misuse")
  io.println("nil status ok")
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-nil-status-') as temporary:
    work = Path(temporary)
    (work / 'main.dyn').write_text(SOURCE)
    for mode in ('--debug', '--release'):
        program = work / ('program' + mode)
        subprocess.run([DYN, 'build', str(work), mode, '--quiet', '--no-cache', '--output', str(program)], check=True, timeout=300)
        result = subprocess.run([str(program)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0 and result.stdout == 'nil status ok\n', (mode, result.returncode, result.stdout, result.stderr)
print('PASS nil status: failures dropped, readers end, writers stop (debug and release)')
