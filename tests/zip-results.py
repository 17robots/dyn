#!/usr/bin/env python3
"""Actual std ZIP results, sticky streaming errors and arena contracts."""
import io
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get("DYN", ROOT / "build/dyn-release")).resolve())

# Generate independent stored ZIP goldens, including the central directory.
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
    for name, payload in (("a", b"hello"), ("empty", b"")):
        entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
        archive.writestr(entry, payload)
data = buffer.getvalue()
literal = '"' + "".join(f"\\x{byte:02x}" for byte in data) + '"'

SOURCE = r'''use zip "std/archive/zip"
use io "std/io"
use mem "std/mem"
use bytes "std/bytes"
fn check(ok: bool) { if !ok { #panic("zip fixture") } }
struct Input { source: []const u8, offset: usize, fail: usize, calls: usize, native: isize }
fn read(data: rawptr, destination: []u8) usize!io.IoErr {
 s := #cast(*Input,data)
 s.calls += 1
 if s.offset == s.fail { fail .WouldBlock }
 take := destination.len
 if take > s.fail - s.offset { take = s.fail - s.offset }
 if take > s.source.len - s.offset { take = s.source.len - s.offset }
 for i in 0..take { destination[i] = s.source[s.offset+i] }
 s.offset += take
 return take
}
// The kinds of failure these fixtures meet; Ok when a call worked.
enum Kind { Ok, NotFound, PermissionDenied, AlreadyExists, InvalidInput, WouldBlock, Interrupted, Unsupported, Capacity, System }
fn kind_of(err: io.IoErr) Kind {
 case err {
  .NotFound => { return Kind.NotFound }
  .PermissionDenied => { return Kind.PermissionDenied }
  .AlreadyExists => { return Kind.AlreadyExists }
  .InvalidInput => { return Kind.InvalidInput }
  .WouldBlock => { return Kind.WouldBlock }
  .Interrupted => { return Kind.Interrupted }
  .Unsupported => { return Kind.Unsupported }
  .Capacity => { return Kind.Capacity }
  .System => { return Kind.System }
 }
}
// The entry a call returned, the reader's offset after it, and whether it
// returned one (the reader's ended, inverted).
struct Next { value: zip.Entry, offset: usize, found: bool }
fn archive_next(state: *zip.ArchiveReader) Next {
 entry := zip.next(state) catch { #panic("zip next") }
 return Next{ value: entry, offset: state.offset, found: !state.ended }
}
fn stream_entry(state: *zip.StreamReader) Next {
 entry := zip.next_stream(state) catch { #panic("zip next_stream") }
 return Next{ value: entry, offset: state.offset, found: !state.ended }
}
fn next_failure(state: *zip.ArchiveReader) Kind {
 _ = zip.next(state) catch err {
  check(!state.ended || state.failed)
  return kind_of(err)
 }
 #panic("zip next should fail")
}
struct Streamed { next: Next, failure: Kind }
fn stream_next(state: *zip.StreamReader) Streamed {
 entry := zip.next_stream(state) catch err {
  return Streamed{ next: Next{ offset: state.offset, found: !state.ended }, failure: kind_of(err) }
 }
 return Streamed{ next: Next{ value: entry, offset: state.offset, found: !state.ended } }
}
fn extract_failure(arena: *mem.Arena, entry: zip.Entry) Kind {
 _ = zip.extract(arena, entry) catch err { return kind_of(err) }
 #panic("zip extract should fail")
}
fn open_fails(data: []const u8) bool {
 _ = zip.open_checked(data) catch { return true }
 return false
}
fn main() {
 invalid_data: [46]u8
 invalid_data[0]=80
 invalid_data[1]=75
 invalid_data[2]=1
 invalid_data[3]=2
 invalid_data[42]=100
 invalid_state := zip.ArchiveReader{source:invalid_data[..],indexed:true,directory_start:200,directory_end:46,remaining:1}
 check(next_failure(&invalid_state) == Kind.InvalidInput && invalid_state.failed)
 invalid_state.source=""
 invalid_state.remaining=0
 check(next_failure(&invalid_state) == Kind.InvalidInput)
 data: []const u8 = DATA
 arena := mem.arena_alloc(0)
 state := zip.open(data)
 first := archive_next(&state)
 check(first.found && first.offset == 36)
 decoded := zip.extract(arena,first.value) catch { #panic("extract") }
 check(bytes.equal(decoded,"hello"))
 mark := mem.arena_used(arena)
 bad := first.value
 bad.checksum = 0
 check(extract_failure(arena,bad) == Kind.InvalidInput && mem.arena_used(arena) == mark)
 empty := archive_next(&state)
 check(empty.found)
 _ = zip.extract(arena,empty.value) catch { #panic("extract") }
 end := archive_next(&state)
 check(!end.found)
 opened := zip.open_checked(data) catch { #panic("open_checked") }
 indexed := archive_next(&opened)
 check(indexed.found && bytes.equal(indexed.value.payload,"hello"))
 check(archive_next(&opened).found)
 check(!archive_next(&opened).found)
 broken := zip.ArchiveReader{ source: data, indexed: true, offset: 0, remaining: 1 }
 check(next_failure(&broken) == Kind.InvalidInput)
 broken.source = data
 check(next_failure(&broken) == Kind.InvalidInput)
 truncated := zip.open(data[..2])
 check(next_failure(&truncated) == Kind.InvalidInput)
 truncated.source = data
 check(next_failure(&truncated) == Kind.InvalidInput)
 header: [30]u8
 name: [64]u8
 payload: [64]u8
 for limit in 0..72 {
   input := Input{ source: data, fail: limit }
   stream := zip.stream_reader(io.Reader{ data: &input, read: read },header[..],name[..],payload[..])
   item := stream_next(&stream)
   for item.next.found { item = stream_next(&stream) }
   check(item.failure == Kind.WouldBlock && item.next.offset == limit)
   calls := input.calls
   again := stream_next(&stream)
   check(again.failure == item.failure && again.next.offset == item.next.offset && input.calls == calls)
 }
 for limit in 0..36 {
   cursor := io.cursor(data[..limit])
   stream := zip.stream_reader(io.cursor_reader(&cursor),header[..],name[..],payload[..])
   item := stream_next(&stream)
   if limit == 0 { check(!item.next.found && item.failure == Kind.Ok) }
   else { check(item.failure == Kind.InvalidInput) }
   check(item.next.offset == limit && !item.next.found)
   again := stream_next(&stream)
   check(again.failure == item.failure && again.next.offset == limit)
 }
 cursor := io.cursor(data[..36])
 stream := zip.stream_reader(io.cursor_reader(&cursor),header[..],name[..],payload[..])
 check(stream_entry(&stream).found)
 check(!stream_entry(&stream).found)
 native_input := Input{ source: data, fail: 32, native: -4 }
 native_stream := zip.stream_reader(io.Reader{ data: &native_input, read: read },header[..],name[..],payload[..])
 native_result := stream_next(&native_stream)
 check(native_result.failure == Kind.WouldBlock && native_result.next.offset == 32)
 check(stream_next(&native_stream).failure == Kind.WouldBlock && native_input.calls == 5)
 overlap := zip.stream_reader(io.Reader{},header[..],header[..],payload[..])
 check(stream_next(&overlap).failure == Kind.InvalidInput)
 capacity := zip.stream_reader(io.Reader{},header[..2],name[..],payload[..])
 check(stream_next(&capacity).failure == Kind.Capacity)
 check(open_fails("x"))
 eof_input := Input{ source: "", fail: 100 }
 eof_stream := zip.stream_reader(io.Reader{ data: &eof_input, read: read },header[..],name[..],payload[..])
 eof := stream_next(&eof_stream)
 check(!eof.next.found && eof.failure == Kind.Ok)
 check(!stream_entry(&eof_stream).found && eof_input.calls == 1)
 check(open_fails(data[data.len-22..]))
 empty_eocd: [22]u8
 empty_eocd[0] = 80
 empty_eocd[1] = 75
 empty_eocd[2] = 5
 empty_eocd[3] = 6
 empty_archive := zip.open_checked(empty_eocd[..]) catch { #panic("open_checked") }
 check(!archive_next(&empty_archive).found)
 empty_cursor := io.cursor(empty_eocd[..])
 empty_stream := zip.stream_reader(io.cursor_reader(&empty_cursor),header[..],name[..],payload[..])
 check(!stream_entry(&empty_stream).found && empty_stream.offset == 22)
 check(!stream_entry(&empty_stream).found && empty_stream.offset == 22)
 zero: Next
 check(!zero.found && zero.offset == 0)
 zero_reader: zip.ArchiveReader
 check(!archive_next(&zero_reader).found)
 check(extract_failure(arena,zip.Entry{ uncompressed_size: ~#cast(usize,0) }) == Kind.Capacity && mem.arena_used(arena) == mark)
}
'''

ARENA_SOURCE = r'''use zip "std/archive/zip"
use mem "std/mem"
fn main() {
 storage: [1+mem.ArenaBufferOverhead]u8
 pad := (16-(#cast(usize,&storage[0])&15))&15
 arena := mem.arena_from_buffer(storage[pad..pad+mem.ArenaHeader+1])
 _ = zip.extract(arena,zip.Entry{ payload: "hello", compressed_size: 5, uncompressed_size: 5 }) catch { #panic("extract") }
}
'''

with tempfile.TemporaryDirectory(prefix="dyn-zip-results-") as temporary:
    root = Path(temporary)
    for name, source, panic in (("results", SOURCE.replace("DATA", literal), False),
                                ("arena", ARENA_SOURCE, True)):
        project = root / name
        project.mkdir()
        (project / "main.dyn").write_text(source, encoding="utf-8")
        output = project / ("program.exe" if os.name == "nt" else "program")
        for mode in ("--debug", "--release"):
            subprocess.run([DYN, "build", str(project), "--no-cache", "--quiet",
                            mode, "--output", str(output)], check=True, timeout=90)
            result = subprocess.run([str(output)], capture_output=True, text=True, timeout=15)
            if panic:
                assert result.returncode == 101 and "arena exhausted" in result.stderr, (
                    name, mode, result.returncode, result.stdout, result.stderr)
            else:
                assert result.returncode == 0, (name, mode, result.stdout, result.stderr)
print("PASS ZIP results, EOF, sticky errors, CRC rollback and arena panic (debug/release)")
