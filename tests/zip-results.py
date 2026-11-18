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

SOURCE = r'''use "std/archive/zip" zip
use "std/fail"
use "std/io" io
use "std/mem" mem
use "std/bytes" bytes
fn check(ok: bool) { if !ok { #panic("zip fixture") } }
struct Input { source: []const u8, offset: usize, fail: usize, calls: usize, native: isize }
fn read(data: rawptr, status: *fail.Status, destination: []u8) usize {
 s := #cast(*Input,data)
 s.calls += 1
 if s.offset == s.fail {
  failure := fail.make(fail.Kind.WouldBlock, "read", "", "would block")
  failure.native = s.native
  fail.set(status, failure)
  return 0
 }
 take := #len(destination)
 if take > s.fail - s.offset { take = s.fail - s.offset }
 if take > #len(s.source) - s.offset { take = #len(s.source) - s.offset }
 for i in 0..take { destination[i] = s.source[s.offset+i] }
 s.offset += take
 return take
}
fn next_failure(state: *zip.ArchiveReader) fail.Failure {
 status: fail.Status
 next := zip.next(&status, state)
 check(!next.found && status.failed)
 return status.failure
}
struct Streamed { next: zip.Next, failure: fail.Failure }
fn stream_next(state: *zip.StreamReader) Streamed {
 status: fail.Status
 next := zip.next_stream(&status, state)
 return Streamed{ next: next, failure: status.failure }
}
fn extract_failure(arena: *mem.Arena, entry: zip.Entry) fail.Failure {
 status: fail.Status
 bytes_out := zip.extract(arena, &status, entry)
 check(status.failed && #len(bytes_out) == 0)
 return status.failure
}
fn open_fails(data: []const u8) bool {
 status: fail.Status
 _ = zip.open_checked(&status, data)
 return status.failed
}
fn main() {
 status := fail.Status{ on_failure: fail.panic_on_failure }
 invalid_data: [46]u8
 invalid_data[0]=80
 invalid_data[1]=75
 invalid_data[2]=1
 invalid_data[3]=2
 invalid_data[42]=100
 invalid_state := zip.ArchiveReader{source:invalid_data[..],indexed:true,directory_start:200,directory_end:46,remaining:1}
 check(next_failure(&invalid_state).kind == fail.Kind.InvalidInput && invalid_state.failed)
 invalid_state.source=""
 invalid_state.remaining=0
 check(next_failure(&invalid_state).kind == fail.Kind.InvalidInput)
 data: []const u8 = DATA
 arena := mem.arena_alloc(0)
 state := zip.open(data)
 first := zip.next(&status, &state)
 check(first.found && first.offset == 36)
 decoded := zip.extract(arena,&status,first.value)
 check(bytes.equal(decoded,"hello"))
 mark := mem.arena_used(arena)
 bad := first.value
 bad.checksum = 0
 check(extract_failure(arena,bad).kind == fail.Kind.InvalidInput && mem.arena_used(arena) == mark)
 empty := zip.next(&status, &state)
 check(empty.found)
 _ = zip.extract(arena,&status,empty.value)
 end := zip.next(&status, &state)
 check(!end.found)
 opened := zip.open_checked(&status, data)
 indexed := zip.next(&status, &opened)
 check(indexed.found && bytes.equal(indexed.value.payload,"hello"))
 check(zip.next(&status, &opened).found)
 check(!zip.next(&status, &opened).found)
 broken := zip.ArchiveReader{ source: data, indexed: true, offset: 0, remaining: 1 }
 check(next_failure(&broken).kind == fail.Kind.InvalidInput)
 broken.source = data
 check(next_failure(&broken).kind == fail.Kind.InvalidInput)
 truncated := zip.open(data[..2])
 check(next_failure(&truncated).kind == fail.Kind.InvalidInput)
 truncated.source = data
 check(next_failure(&truncated).kind == fail.Kind.InvalidInput)
 header: [30]u8
 name: [64]u8
 payload: [64]u8
 for limit in 0..72 {
   input := Input{ source: data, fail: limit }
   stream := zip.stream_reader(io.Reader{ data: &input, read: read },header[..],name[..],payload[..])
   item := stream_next(&stream)
   for item.next.found { item = stream_next(&stream) }
   check(item.failure.kind == fail.Kind.WouldBlock && item.failure.native == 0 && item.next.offset == limit)
   calls := input.calls
   again := stream_next(&stream)
   check(again.failure.kind == item.failure.kind && again.next.offset == item.next.offset && input.calls == calls)
 }
 for limit in 0..36 {
   cursor := io.cursor(data[..limit])
   stream := zip.stream_reader(io.cursor_reader(&cursor),header[..],name[..],payload[..])
   item := stream_next(&stream)
   if limit == 0 { check(!item.next.found && item.failure.kind == fail.Kind.Ok) }
   else { check(item.failure.kind == fail.Kind.InvalidInput) }
   check(item.next.offset == limit && !item.next.found)
   again := stream_next(&stream)
   check(again.failure.kind == item.failure.kind && again.next.offset == limit)
 }
 cursor := io.cursor(data[..36])
 stream := zip.stream_reader(io.cursor_reader(&cursor),header[..],name[..],payload[..])
 check(zip.next_stream(&status, &stream).found)
 check(!zip.next_stream(&status, &stream).found)
 native_input := Input{ source: data, fail: 32, native: -4 }
 native_stream := zip.stream_reader(io.Reader{ data: &native_input, read: read },header[..],name[..],payload[..])
 native_result := stream_next(&native_stream)
 check(native_result.failure.kind == fail.Kind.WouldBlock && native_result.failure.native == -4 && native_result.next.offset == 32)
 check(stream_next(&native_stream).failure.native == -4 && native_input.calls == 5)
 overlap := zip.stream_reader(io.Reader{},header[..],header[..],payload[..])
 check(stream_next(&overlap).failure.kind == fail.Kind.InvalidInput)
 capacity := zip.stream_reader(io.Reader{},header[..2],name[..],payload[..])
 check(stream_next(&capacity).failure.kind == fail.Kind.Capacity)
 check(open_fails("x"))
 eof_input := Input{ source: "", fail: 100 }
 eof_stream := zip.stream_reader(io.Reader{ data: &eof_input, read: read },header[..],name[..],payload[..])
 eof := stream_next(&eof_stream)
 check(!eof.next.found && eof.failure.kind == fail.Kind.Ok)
 check(!zip.next_stream(&status, &eof_stream).found && eof_input.calls == 1)
 check(open_fails(data[#len(data)-22..]))
 empty_eocd: [22]u8
 empty_eocd[0] = 80
 empty_eocd[1] = 75
 empty_eocd[2] = 5
 empty_eocd[3] = 6
 empty_archive := zip.open_checked(&status, empty_eocd[..])
 check(!zip.next(&status, &empty_archive).found)
 empty_cursor := io.cursor(empty_eocd[..])
 empty_stream := zip.stream_reader(io.cursor_reader(&empty_cursor),header[..],name[..],payload[..])
 check(!zip.next_stream(&status, &empty_stream).found && empty_stream.offset == 22)
 check(!zip.next_stream(&status, &empty_stream).found && empty_stream.offset == 22)
 zero: zip.Next
 check(!zero.found && zero.offset == 0)
 zero_reader: zip.ArchiveReader
 check(!zip.next(&status, &zero_reader).found)
 check(extract_failure(arena,zip.Entry{ uncompressed_size: ~#cast(usize,0) }).kind == fail.Kind.Overflow && mem.arena_used(arena) == mark)
}
'''

ARENA_SOURCE = r'''use "std/archive/zip" zip
use "std/fail"
use "std/mem" mem
fn main() {
 status: fail.Status
 storage: [1+mem.ArenaBufferOverhead]u8
 pad := (16-(#cast(usize,&storage[0])&15))&15
 arena := mem.arena_from_buffer(storage[pad..pad+mem.ArenaHeader+1])
 _ = zip.extract(arena,&status,zip.Entry{ payload: "hello", compressed_size: 5, uncompressed_size: 5 })
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
