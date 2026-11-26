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
use "std/sync"
fn require(value: bool, message: []const u8) { if !value { io.eprintln("{}", message)
#panic(message) } }
fn lines(text: []const u8, expected: []const u8, buffering: usize) {
  cursor := io.cursor(text)
  scratch: [16]u8
  input := bufio.reader(io.cursor_reader(&cursor), scratch[..buffering])
  result: [256]u8
  used: usize = 0
  for {
    line := bufio.read_line(&input) catch { #panic("stdlib assertion 30") }
    if input.ended { break }
    for byte in line {
      result[used] = byte
      used += 1
    }
    result[used] = '|'
    used += 1
  }
  require(bytes.equal(result[..used], expected), "stdlib assertion 35")
}
fn error_read(data: rawptr, destination: []u8) usize!io.IoErr {
  _ = data
  destination[0] = 'x'
  fail .PermissionDenied
}
fn error_write(data: rawptr, source: []const u8) usize!io.IoErr {
  _ = data
  _ = source
  fail .PermissionDenied
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
  arguments := process.arguments(arena) catch { #panic("cannot read arguments") }
  require(arguments.len == 7, "stdlib assertion 49")
  require(bytes.equal(arguments[1], "space argument"), "stdlib assertion 50")
  require(bytes.equal(arguments[2], ""), "stdlib assertion 51")
  require(bytes.equal(arguments[3], "quote\"inside"), "stdlib assertion 52")
  require(bytes.equal(arguments[4], "trailing\\"), "stdlib assertion 53")
  require(bytes.equal(arguments[5], "café 😀"), "stdlib assertion 54")
  require(bytes.equal(arguments[6], "slashes\\\\\"quote"), "stdlib assertion 55")
  tiny_backing: [1+mem.ArenaBufferOverhead]u8
  tiny_pad := (16-(#cast(usize,&tiny_backing[0])&15))&15
  tiny := mem.arena_from_buffer(tiny_backing[tiny_pad..tiny_pad+mem.ArenaHeader+1])
  unopened := fs.File{}
  require(!fs.is_open(&unopened), "stdlib assertion 61")
  fs.close(&unopened)
  require(fails_with(read_unopened(&unopened, tiny_backing[..]), 4), "stdlib assertion 63")
  require(fails_with(open_kind("missing-file"), 1), "stdlib assertion 65")
  created := fs.create_exclusive("café-😀.txt") catch { #panic("stdlib assertion 67") }
  require(fails_with(create_kind("café-😀.txt"), 3), "stdlib assertion 69")
  io.write(fs.writer(&created), "abc") catch { #panic("stdlib assertion 72") }
  fs.sync(&created) catch { #panic("stdlib assertion 73") }
  moved := created
  fs.close(&moved)
  require(!fs.is_open(&moved), "stdlib assertion 75")
  fs.close(&moved)
  appended := fs.append("café-😀.txt") catch { #panic("stdlib assertion 79") }
  fs.write(&appended, "def") catch { #panic("stdlib assertion 79") }
  fs.close(&appended)
  opened := fs.open("café-😀.txt") catch { #panic("stdlib assertion 82") }
  require((fs.seek(&opened, 2, 0) catch 0) == 2, "stdlib assertion 82")
  contents: [8]u8
  read := io.read_exact(fs.reader(&opened), contents[..4]) catch 0
  require(read == 4 && bytes.equal(contents[..4], "cdef"), "stdlib assertion 85")
  require((io.read(fs.reader(&opened), contents[..]) catch 9) == 0, "stdlib assertion 86")
  fs.close(&opened)
  mark := mem.arena_mark(arena)
  require(fails_with(read_all_kind(arena, "café-😀.txt", 5), 5) && mem.arena_mark(arena) == mark, "stdlib assertion 90")
  all := fs.read_all(arena, "café-😀.txt", 6) catch { #panic("stdlib assertion 94") }
  require(bytes.equal(all, "abcdef"), "stdlib assertion 94")
  require(fs_write_file("café-😀.txt", "z"), "stdlib assertion 95")
  truncated := fs.read_all(arena, "café-😀.txt", 1) catch { #panic("stdlib assertion 97") }
  require(bytes.equal(truncated, "z"), "stdlib assertion 97")
  buffering: usize = 12
  for buffering <= 16 {
    lines("abc\r\n\nlonger line\nlast", "abc||longer line|last|", buffering)
    lines("\r\n\r\r\nx\ry\n\r", "|\r|x\ry|\r|", buffering)
    lines("12345678\n", "12345678|", buffering)
    lines("", "", buffering)
    buffering += 1
  }
  // A line longer than the storage fails with Capacity; the next read
  // continues after it.
  long_cursor := io.cursor("ab\nlonger\ncd")
  long_storage: [4]u8
  long_input := bufio.reader(io.cursor_reader(&long_cursor), long_storage[..])
  first_line := bufio.read_line(&long_input) catch { #panic("stdlib assertion 111") }
  require(bytes.equal(first_line, "ab"), "stdlib assertion 111")
  require(line_kind(&long_input) == 5, "stdlib assertion 112")
  after_line := bufio.read_line(&long_input) catch { #panic("stdlib assertion 113") }
  require(!long_input.ended && bytes.equal(after_line, "cd"), "stdlib assertion 113")
  _ = bufio.read_line(&long_input) catch { #panic("stdlib assertion 113b") }
  require(long_input.ended, "stdlib assertion 113b")
  error_storage: [8]u8
  failing := bufio.reader(io.Reader{ read: error_read }, error_storage[..])
  require(line_kind(&failing) == 2, "stdlib assertion 115")
  no_storage := bufio.reader(io.Reader{ read: error_read }, error_storage[..0])
  require(line_kind(&no_storage) == 4, "stdlib assertion 116")
  failed_output := bufio.writer(io.Writer{ write: error_write }, error_storage[..])
  io.write(bufio.writer_adapter(&failed_output), "pending") catch { #panic("stdlib assertion 118") }
  require(flush_kind(&failed_output) == 2 && failed_output.used == 7, "stdlib assertion 119")
  require(flush_kind(&failed_output) == 2 && failed_output.used == 7, "stdlib assertion 120")
  raw_cursor := io.cursor("a\r\nx")
  raw_input := bufio.reader(io.cursor_reader(&raw_cursor), error_storage[..1])
  raw_line := bufio.read_until(&raw_input, contents[..], 10) catch { #panic("stdlib assertion 125") }
  require(raw_line.status == bufio.ReadStatus.Complete && bytes.equal(contents[..raw_line.transferred], "a\r"), "stdlib assertion 125")
  require(fails_with(environment_kind(arena, ""), 4), "stdlib assertion 126")
  invalid_child := process.Child{}
  require(fails_with(wait_kind(&invalid_child), 4), "stdlib assertion 128")
  minimum: isize = 0 - #cast(isize, (#max(usize) >> 1)) - 1
  require(kind_of(io.linux_err(minimum)) == 9, "stdlib assertion 130")
  require(kind_of(io.darwin_err(minimum)) == 9, "stdlib assertion 131")
  require(kind_of(io.windows_err(minimum)) == 9, "stdlib assertion 132")
  require(kind_of(io.wasi_err(minimum)) == 9, "stdlib assertion 133")
  started := time.monotonic_now()
  wall := time.realtime_now()
  require(wall.seconds > 1700000000, "stdlib assertion 136")
  time.sleep(time.Millisecond * 2)
  finished := time.monotonic_now()
  require(time.elapsed(started, finished) >= time.Millisecond, "stdlib assertion 139")
  time.sleep(0)
  io.println_to(io.stdout(), "stdlib passed") catch { #panic("stdlib assertion 141") }
}

// Writes data to path; whether it worked.
fn fs_write_file(path: []const u8, data: []const u8) bool {
  fs.write_all(path, data) catch { return false }
  return true
}

// 0 for success; 1 NotFound, 3 AlreadyExists, 4 InvalidInput, 5 Capacity,
// 6 anything else.
fn kind_of(err: io.IoErr) u8 {
  case err {
    .NotFound => { return 1 }
    .PermissionDenied => { return 2 }
    .AlreadyExists => { return 3 }
    .InvalidInput => { return 4 }
    .Capacity => { return 5 }
    .System(_) => { return 9 }
    _ => { return 6 }
  }
}
fn line_kind(reader: *bufio.Reader) u8 {
  _ = bufio.read_line(reader) catch err { return kind_of(err) }
  return 0
}
fn flush_kind(writer: *bufio.Writer) u8 {
  bufio.writer_flush(writer) catch err { return kind_of(err) }
  return 0
}
fn fails_with(kind: u8, expected: u8) bool {
  return kind == expected
}
fn read_unopened(file: *fs.File, destination: []u8) u8 {
  _ = fs.read(file, destination) catch err { return kind_of(err) }
  return 0
}
fn open_kind(path: []const u8) u8 {
  file := fs.open(path) catch err { return kind_of(err) }
  fs.close(&file)
  return 0
}
fn create_kind(path: []const u8) u8 {
  file := fs.create_exclusive(path) catch err { return kind_of(err) }
  fs.close(&file)
  return 0
}
fn read_all_kind(arena: *mem.Arena, path: []const u8, maximum: usize) u8 {
  _ = fs.read_all(arena, path, maximum) catch err { return kind_of(err) }
  return 0
}
fn environment_kind(arena: *mem.Arena, name: []const u8) u8 {
  _ = process.environment(arena, name) catch err { return kind_of(err) }
  return 0
}
fn wait_kind(child: *process.Child) u8 {
  _ = process.wait(child, false) catch err { return kind_of(err) }
  return 0
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
