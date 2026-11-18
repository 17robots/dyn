#!/usr/bin/env python3
"""Execute portable stdlib contracts on the current host and installed SDK."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build'/('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve()
SOURCE = r'''use "std/fail"
use "std/fs"
use "std/io"
use "std/bufio"
use "std/process"
use "std/time"
use "std/mem"
use "std/bytes"
use "std/io" errors
use "std/sync"
fn require(value: bool, message: []const u8) { if !value { io.eprintln("{}", message)
#panic(message) } }
fn lines(text: []const u8, expected: []const u8, capacity: usize, buffering: usize) {
  cursor := io.cursor(text)
  scratch: [8]u8
  input := bufio.reader(io.cursor_reader(&cursor), scratch[..buffering])
  chunk: [8]u8
  result: [256]u8
  used: usize = 0
  status: fail.Status
  empty := bufio.read_line(&status, &input, chunk[..0])
  require(empty.status == bufio.ReadStatus.More && empty.transferred == 0, "stdlib assertion 27")
  for {
    part := bufio.read_line(&status, &input, chunk[..capacity])
    require(!status.failed, "stdlib assertion 30")
    for byte in chunk[..part.transferred] { result[used] = byte
    used += 1 }
    if part.status == bufio.ReadStatus.Complete { result[used] = '|'
    used += 1 }
    if part.status == bufio.ReadStatus.End { break }
  }
  require(bytes.equal(result[..used], expected), "stdlib assertion 35")
}
fn error_read_transfer(data: rawptr, destination: []u8) io.Transfer {
  _ = data
  destination[0] = 'x'
  return io.Transfer{ transferred: 1, failure: io.Failure{ kind: errors.Kind.PermissionDenied } }
}
fn error_read(data: rawptr, status: *fail.Status, destination: []u8) usize {
  return io.from_transfer(status, error_read_transfer(data, destination), "read", "")
}
fn error_write_transfer(data: rawptr, source: []const u8) io.Transfer {
  _ = data
  _ = source
  return io.Transfer{ failure: io.Failure{ kind: errors.Kind.PermissionDenied } }
}
fn error_write(data: rawptr, status: *fail.Status, source: []const u8) usize {
  return io.from_transfer(status, error_write_transfer(data, source), "write", "")
}
fn main() {
  counter32 := sync.atomic_u32(7)
  require(sync.load_u32(&counter32) == 7, "atomic32 initial")
  sync.store_u32(&counter32, 9)
  require(sync.exchange_u32(&counter32, 11) == 9, "atomic32 exchange")
  require(sync.fetch_add_u32(&counter32, 2) == 11, "atomic32 add")
  require(!sync.compare_exchange_u32(&counter32, 11, 0), "atomic32 failed CAS")
  require(sync.compare_exchange_u32(&counter32, 13, 17), "atomic32 CAS")
  require(sync.load_u32(&counter32) == 17, "atomic32 final")
  counter64 := sync.atomic_u64(4294967296)
  require(sync.load_u64(&counter64) == 4294967296, "atomic64 initial")
  sync.store_u64(&counter64, 4294967297)
  require(sync.exchange_u64(&counter64, 4294967298) == 4294967297, "atomic64 exchange")
  require(sync.fetch_add_u64(&counter64, 2) == 4294967298, "atomic64 add")
  require(!sync.compare_exchange_u64(&counter64, 4294967298, 0), "atomic64 failed CAS")
  require(sync.compare_exchange_u64(&counter64, 4294967300, 17), "atomic64 CAS")
  require(sync.load_u64(&counter64) == 17, "atomic64 final")
  backing: [131072+mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(backing[..])
  arguments := process.arguments(arena)
  require(!errors.failed(arguments.failure) && #len(arguments.value) == 7, "stdlib assertion 49")
  require(bytes.equal(arguments.value[1], "space argument"), "stdlib assertion 50")
  require(bytes.equal(arguments.value[2], ""), "stdlib assertion 51")
  require(bytes.equal(arguments.value[3], "quote\"inside"), "stdlib assertion 52")
  require(bytes.equal(arguments.value[4], "trailing\\"), "stdlib assertion 53")
  require(bytes.equal(arguments.value[5], "café 😀"), "stdlib assertion 54")
  require(bytes.equal(arguments.value[6], "slashes\\\\\"quote"), "stdlib assertion 55")
  tiny_backing: [1+mem.ArenaBufferOverhead]u8
  tiny_pad := (16-(#cast(usize,&tiny_backing[0])&15))&15
  tiny := mem.arena_from_buffer(tiny_backing[tiny_pad..tiny_pad+mem.ArenaHeader+1])
  unopened := fs.File{}
  require(!fs.is_open(&unopened), "stdlib assertion 61")
  fs.close(&unopened)
  unopened_status: fail.Status
  require(fs.read(&unopened_status, &unopened, tiny_backing[..]) == 0 && unopened_status.failure.kind == errors.Kind.InvalidState, "stdlib assertion 63")
  missing: fail.Status
  _ = fs.open(&missing, "missing-file")
  require(missing.failed && missing.failure.kind == errors.Kind.NotFound && missing.failure.native != 0, "stdlib assertion 65")
  status: fail.Status
  created := fs.create_exclusive(&status, "café-😀.txt")
  require(!status.failed, "stdlib assertion 67")
  duplicate: fail.Status
  _ = fs.create_exclusive(&duplicate, "café-😀.txt")
  require(duplicate.failed && duplicate.failure.kind == errors.Kind.AlreadyExists, "stdlib assertion 69")
  require(io.complete(io.write_transfer(fs.writer(&created), "abc")), "stdlib assertion 72")
  fs.sync(&status, &created)
  require(!status.failed, "stdlib assertion 73")
  moved := created
  fs.close(&moved)
  require(!fs.is_open(&moved), "stdlib assertion 75")
  fs.close(&moved)
  appended := fs.append(&status, "café-😀.txt")
  fs.write(&status, &appended, "def")
  require(!status.failed, "stdlib assertion 79")
  fs.close(&appended)
  opened := fs.open(&status, "café-😀.txt")
  require(fs.seek(&status, &opened, 2, 0) == 2 && !status.failed, "stdlib assertion 82")
  contents: [8]u8
  read := io.read_exact_transfer(fs.reader(&opened), contents[..4])
  require((read.status == io.Status.Complete && !io.failed(read.failure)) && bytes.equal(contents[..4], "cdef"), "stdlib assertion 85")
  require(io.read_transfer(fs.reader(&opened), contents[..]).status == io.Status.End, "stdlib assertion 86")
  fs.close(&opened)
  mark := mem.arena_mark(arena)
  bounded_file: fail.Status
  bounded := fs.read_all(arena, &bounded_file, "café-😀.txt", 5)
  require(bounded_file.failed && bounded_file.failure.kind == errors.Kind.Overflow && mem.arena_mark(arena) == mark, "stdlib assertion 90")
  exhausted_file: fail.Status
  exhausted := fs.read_all(tiny, &exhausted_file, "café-😀.txt", 100)
  require(exhausted_file.failed && exhausted_file.failure.kind == errors.Kind.Capacity && mem.arena_mark(tiny) == mem.arena_start(tiny), "stdlib assertion 92")
  all_file: fail.Status
  all := fs.read_all(arena, &all_file, "café-😀.txt", 6)
  require(!all_file.failed && bytes.equal(all, "abcdef"), "stdlib assertion 94")
  require(fs_write_file("café-😀.txt", "z"), "stdlib assertion 95")
  truncated_file: fail.Status
  truncated := fs.read_all(arena, &truncated_file, "café-😀.txt", 1)
  require(!truncated_file.failed && bytes.equal(truncated, "z"), "stdlib assertion 97")
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
  error_storage: [8]u8
  for error_capacity in [0, 8] {
    failing := bufio.reader(io.Reader{ read: error_read }, error_storage[..#cast(usize, error_capacity)])
    failing_status: fail.Status
    error_line := bufio.read_line(&failing_status, &failing, contents[..])
    require(failing_status.failed && error_line.transferred == 1, "stdlib assertion 114")
    require(contents[0] == 'x' && failing_status.failure.kind == errors.Kind.PermissionDenied && failing_status.failure.native == 0, "stdlib assertion 115")
  }
  failed_output := bufio.writer(io.Writer{ write: error_write }, error_storage[..])
  require(io.complete(io.write_transfer(bufio.writer_adapter(&failed_output), "pending")), "stdlib assertion 118")
  flush_status: fail.Status
  bufio.writer_flush(&flush_status, &failed_output)
  require(flush_status.failure.kind == errors.Kind.PermissionDenied && failed_output.used == 7, "stdlib assertion 119")
  retry: fail.Status
  bufio.writer_flush(&retry, &failed_output)
  require(retry.failure.kind == errors.Kind.PermissionDenied && failed_output.used == 7, "stdlib assertion 120")
  raw_cursor := io.cursor("a\r\nx")
  raw_input := bufio.reader(io.cursor_reader(&raw_cursor), error_storage[..1])
  raw_status: fail.Status
  raw_line := bufio.read_until(&raw_status, &raw_input, contents[..], 10)
  require(raw_line.status == bufio.ReadStatus.Complete && !raw_status.failed && bytes.equal(contents[..raw_line.transferred], "a\r"), "stdlib assertion 125")
  require(process.environment(arena, "").failure.kind == errors.Kind.InvalidInput, "stdlib assertion 126")
  invalid_child := process.Child{}
  require(process.wait(&invalid_child, false).failure.kind == errors.Kind.InvalidState, "stdlib assertion 128")
  minimum: isize = 0 - #cast(isize, (#max(usize) >> 1)) - 1
  require(errors.linux(minimum) == errors.Kind.System, "stdlib assertion 130")
  require(errors.darwin(minimum) == errors.Kind.System, "stdlib assertion 131")
  require(errors.windows(minimum) == errors.Kind.System, "stdlib assertion 132")
  require(errors.wasi(minimum) == errors.Kind.System, "stdlib assertion 133")
  started := time.monotonic_now()
  wall := time.realtime_now()
  require(!errors.failed(started.failure) && !errors.failed(wall.failure) && wall.value.seconds > 1700000000, "stdlib assertion 136")
  require(!errors.failed(time.sleep(time.Millisecond * 2).failure), "stdlib assertion 137")
  finished := time.monotonic_now()
  require(!errors.failed(finished.failure) && time.elapsed(started.value, finished.value).value >= time.Millisecond, "stdlib assertion 139")
  require(!errors.failed(time.sleep(0).failure), "stdlib assertion 140")
  printed: fail.Status
  io.println_to(&printed, io.stdout(), "stdlib passed")
  require(!printed.failed, "stdlib assertion 141")
}

// Writes data to path; whether it worked.
fn fs_write_file(path: []const u8, data: []const u8) bool {
  status: fail.Status
  fs.write_all(&status, path, data)
  return !status.failed
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
print('PASS portable stdlib: atomics, files, ownership, arguments, clocks and buffered lines')
