#!/usr/bin/env python3
"""Execute portable stdlib contracts on the current host and installed SDK."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build'/('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve()
SOURCE = r'''use "std/fs"
use "std/io"
use "std/bufio"
use "std/process"
use "std/time"
use "std/mem"
use "std/bytes"
use "std/errors"
fn require(value: bool, message: []const u8) { if !value { _ = io.println(io.stderr(), "{}", message) #panic(message) } }
fn lines(text: []const u8, expected: []const u8, capacity: usize, buffering: usize) {
  cursor := io.cursor(text)
  scratch: [8]u8 = []
  input := bufio.reader(io.cursor_reader(&cursor), scratch[..buffering])
  chunk: [8]u8 = []
  result: [256]u8 = []
  used: usize = 0
  empty := bufio.read_line(&input, chunk[..0])
  require(empty.status == bufio.ReadStatus.More && empty.transferred == 0, "stdlib assertion 27")
  for {
    part := bufio.read_line(&input, chunk[..capacity])
    require(part.status != bufio.ReadStatus.Error, "stdlib assertion 30")
    for byte in chunk[..part.transferred] { result[used] = byte used += 1 }
    if part.status == bufio.ReadStatus.Complete { result[used] = '|' used += 1 }
    if part.status == bufio.ReadStatus.End { break }
  }
  require(bytes.equal(result[..used], expected), "stdlib assertion 35")
}
fn error_read(data: rawptr, destination: []u8) io.Result {
  _ = data destination[0] = 'x'
  return io.Result{ transferred: 1, kind: errors.Kind.PermissionDenied, status: io.Status.Error }
}
fn error_write(data: rawptr, source: []const u8) io.Result {
  _ = data _ = source
  return io.Result{ kind: errors.Kind.PermissionDenied, status: io.Status.Error }
}
fn main() {
  backing: [131072]u8 = []
  arena := mem.arena_from_buffer(backing[..])
  arguments := process.arguments(&arena)
  require(arguments.ok && #len(arguments.values) == 7, "stdlib assertion 49")
  require(bytes.equal(arguments.values[1], "space argument"), "stdlib assertion 50")
  require(bytes.equal(arguments.values[2], ""), "stdlib assertion 51")
  require(bytes.equal(arguments.values[3], "quote\"inside"), "stdlib assertion 52")
  require(bytes.equal(arguments.values[4], "trailing\\"), "stdlib assertion 53")
  require(bytes.equal(arguments.values[5], "café 😀"), "stdlib assertion 54")
  require(bytes.equal(arguments.values[6], "slashes\\\\\"quote"), "stdlib assertion 55")
  tiny_backing: [1]u8 = []
  tiny := mem.arena_from_buffer(tiny_backing[..])
  rejected := process.arguments(&tiny)
  require(!rejected.ok && mem.arena_mark(&tiny) == 0, "stdlib assertion 59")
  unopened := fs.File{}
  require(!fs.is_open(&unopened), "stdlib assertion 61")
  require(fs.close(&unopened).kind == errors.Kind.InvalidState, "stdlib assertion 62")
  require(fs.read(&unopened, tiny_backing[..]).kind == errors.Kind.InvalidState, "stdlib assertion 63")
  missing := fs.open("missing-file")
  require(!missing.ok && missing.kind == errors.Kind.NotFound && missing.error != 0, "stdlib assertion 65")
  created := fs.create_exclusive("café-😀.txt")
  require(created.ok, "stdlib assertion 67")
  duplicate := fs.create_exclusive("café-😀.txt")
  require(!duplicate.ok && duplicate.kind == errors.Kind.AlreadyExists, "stdlib assertion 69")
  borrowed := fs.borrow(&created.file)
  require(fs.close(&borrowed).kind == errors.Kind.InvalidState, "stdlib assertion 71")
  require(io.write_all(fs.writer(&borrowed), "abc").status == io.Status.Complete, "stdlib assertion 72")
  require(fs.sync(&created.file).ok, "stdlib assertion 73")
  moved := fs.take(&created.file)
  require(!fs.is_open(&created.file) && fs.is_open(&moved), "stdlib assertion 75")
  require(fs.close(&moved).ok, "stdlib assertion 76")
  require(fs.close(&moved).kind == errors.Kind.InvalidState, "stdlib assertion 77")
  appended := fs.append("café-😀.txt")
  require(appended.ok && fs.write(&appended.file, "def").ok, "stdlib assertion 79")
  require(fs.close(&appended.file).ok, "stdlib assertion 80")
  opened := fs.open("café-😀.txt")
  require(opened.ok && fs.seek(&opened.file, 2, 0).offset == 2, "stdlib assertion 82")
  contents: [8]u8 = []
  read := io.read_exact(fs.reader(&opened.file), contents[..4])
  require(read.status == io.Status.Complete && bytes.equal(contents[..4], "cdef"), "stdlib assertion 85")
  require(io.read(fs.reader(&opened.file), contents[..]).status == io.Status.End, "stdlib assertion 86")
  require(fs.close(&opened.file).ok, "stdlib assertion 87")
  mark := mem.arena_mark(&arena)
  bounded := fs.read_all(&arena, "café-😀.txt", 5)
  require(!bounded.ok && bounded.kind == errors.Kind.Overflow && mem.arena_mark(&arena) == mark, "stdlib assertion 90")
  exhausted := fs.read_all(&tiny, "café-😀.txt", 100)
  require(!exhausted.ok && exhausted.kind == errors.Kind.Capacity && mem.arena_mark(&tiny) == 0, "stdlib assertion 92")
  all := fs.read_all(&arena, "café-😀.txt", 6)
  require(all.ok && bytes.equal(all.data, "abcdef"), "stdlib assertion 94")
  require(fs.write_all("café-😀.txt", "z").ok, "stdlib assertion 95")
  truncated := fs.read_all(&arena, "café-😀.txt", 1)
  require(truncated.ok && bytes.equal(truncated.data, "z"), "stdlib assertion 97")
  buffering: usize = 0
  for buffering <= 8 {
    capacity: usize = 1
    for capacity <= 8 {
      lines("abc\r\n\nlonger line\nlast", "abc||longer line|last", capacity, buffering)
      lines("\r\n\r\r\nx\ry\n\r", "|\r|x\ry|\r", capacity, buffering)
      lines("12345678\n", "12345678|", capacity, buffering)
      lines("", "", capacity, buffering)
      capacity += 1
    }
    buffering += 1
  }
  error_storage: [8]u8 = []
  for error_capacity in [0, 8] {
    failing := bufio.reader(io.Reader{ read: &error_read }, error_storage[..#cast(usize) error_capacity])
    error_line := bufio.read_line(&failing, contents[..])
    require(error_line.status == bufio.ReadStatus.Error && error_line.transferred == 1, "stdlib assertion 114")
    require(contents[0] == 'x' && error_line.kind == errors.Kind.PermissionDenied && error_line.error == 0, "stdlib assertion 115")
  }
  failed_output := bufio.writer(io.Writer{ write: &error_write }, error_storage[..])
  require(io.write_all(bufio.writer_adapter(&failed_output), "pending").status == io.Status.Complete, "stdlib assertion 118")
  require(bufio.writer_flush(&failed_output).kind == errors.Kind.PermissionDenied, "stdlib assertion 119")
  require(bufio.writer_flush(&failed_output).kind == errors.Kind.PermissionDenied, "stdlib assertion 120")
  require(io.write_all(bufio.writer_adapter(&failed_output), "x").status == io.Status.Error, "stdlib assertion 121")
  raw_cursor := io.cursor("a\r\nx")
  raw_input := bufio.reader(io.cursor_reader(&raw_cursor), error_storage[..1])
  raw_line := bufio.read_until(&raw_input, contents[..], 10)
  require(raw_line.status == bufio.ReadStatus.Complete && bytes.equal(contents[..raw_line.transferred], "a\r"), "stdlib assertion 125")
  require(process.environment("", contents[..]).kind == errors.Kind.InvalidInput, "stdlib assertion 126")
  invalid_child := process.Child{}
  require(process.wait(&invalid_child, false).kind == errors.Kind.InvalidState, "stdlib assertion 128")
  minimum: isize = 0 - #cast(isize) ((~#cast(usize) 0) >> 1) - 1
  require(errors.linux(minimum) == errors.Kind.System, "stdlib assertion 130")
  require(errors.darwin(minimum) == errors.Kind.System, "stdlib assertion 131")
  require(errors.windows(minimum) == errors.Kind.System, "stdlib assertion 132")
  require(errors.wasi(minimum) == errors.Kind.System, "stdlib assertion 133")
  started := time.try_monotonic_now()
  wall := time.try_realtime_now()
  require(started.ok && wall.ok && wall.value.seconds > 1700000000, "stdlib assertion 136")
  require(time.sleep_result(time.Millisecond * 2).ok, "stdlib assertion 137")
  finished := time.try_monotonic_now()
  require(finished.ok && time.elapsed(started.value, finished.value).value >= time.Millisecond, "stdlib assertion 139")
  require(time.sleep_result(0).ok, "stdlib assertion 140")
  require(io.println(io.stdout(), "stdlib passed").status == io.Status.Complete, "stdlib assertion 141")
}
'''

def run(*command, cwd):
    result = subprocess.run(list(map(str, command)), cwd=cwd, capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f'{command!r}: {result.returncode}\n{result.stdout!r}\n{result.stderr!r}')
    return result

with tempfile.TemporaryDirectory(prefix='dyn-stdlib-') as temporary:
    work = Path(temporary)
    project = work/'project'; project.mkdir()
    (project/'main.dyn').write_text(SOURCE, encoding='utf-8')
    for options in ([], ['--release']):
        output = work/('stdlib with spaces.exe' if os.name == 'nt' else 'stdlib with spaces')
        run(DYN, 'build', project, '--no-cache', '--quiet', '--output', output, *options, cwd=work)
        (work/'café-😀.txt').unlink(missing_ok=True)
        result = run(output, 'space argument', '', 'quote"inside', 'trailing\\', 'café 😀', 'slashes\\\\"quote', cwd=work)
        assert result.stdout == b'stdlib passed\n', result.stdout
print('PASS portable stdlib: files, ownership, arguments, clocks and buffered lines')
