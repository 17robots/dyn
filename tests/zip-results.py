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
use "std/io" errors
use "std/parse" parse
use "std/io" io
use "std/mem" mem
use "std/bytes" bytes
fn check(ok: bool) { if !ok { #panic("zip fixture") } }
struct Input { source: []const u8, offset: usize, fail: usize, calls: usize, native: isize }
fn read(data: rawptr, destination: []u8) io.Transfer {
 s := #cast(*Input,data)
 s.calls += 1
 take := #len(destination)
 if take > s.fail - s.offset { take = s.fail - s.offset }
 if take > #len(s.source) - s.offset { take = #len(s.source) - s.offset }
 for i in 0..take { destination[i] = s.source[s.offset+i] }
 s.offset += take
 if s.offset == s.fail { return io.Transfer{ transferred: take, failure: io.Failure{ kind: errors.Kind.WouldBlock, native: s.native } } }
 if s.offset == #len(s.source) { return io.Transfer{ transferred: take, status: io.Status.End } }
 return io.Transfer{ transferred: take }
}
fn main() {
 invalid_data: [46]u8
 invalid_data[0]=80
 invalid_data[1]=75
 invalid_data[2]=1
 invalid_data[3]=2
 invalid_data[42]=100
 invalid_state := zip.ArchiveReader{source:invalid_data[..],indexed:true,directory_start:200,directory_end:46,remaining:1}
 invalid := zip.next(&invalid_state)
 check(!invalid.found && invalid.failure.parse.kind == parse.Kind.Syntax && invalid_state.failed)
 invalid_state.source=""
 invalid_state.remaining=0
 replay_invalid:=zip.next(&invalid_state)
 check(!replay_invalid.found && replay_invalid.failure.parse.kind == parse.Kind.Syntax)
 data: []const u8 = DATA
 arena := mem.arena_alloc(0)
 state := zip.open(data)
 first := zip.next(&state)
 check(first.found && first.failure.kind == parse.StreamKind.Ok && first.offset == 36)
 decoded := zip.extract(arena,first.value)
 check(decoded.failure.kind == parse.Kind.Ok && bytes.equal(decoded.value,"hello") && decoded.failure.kind == parse.Kind.Ok)
 mark := mem.arena_used(arena)
 bad := first.value
 bad.checksum = 0
 crc := zip.extract(arena,bad)
 check(crc.failure.kind != parse.Kind.Ok && crc.failure.kind == parse.Kind.Checksum && #len(crc.value) == 0 && mem.arena_used(arena) == mark)
 empty := zip.next(&state)
 check(empty.found && zip.extract(arena,empty.value).failure.kind == parse.Kind.Ok)
 end := zip.next(&state)
 check(!end.found && end.failure.kind == parse.StreamKind.Ok)
 opened := zip.open_checked(data)
 check(opened.failure.kind == parse.Kind.Ok)
 indexed := zip.next(&opened.value)
 check(indexed.found && bytes.equal(indexed.value.payload,"hello"))
 check(zip.next(&opened.value).found)
 check(!zip.next(&opened.value).found)
 broken := zip.ArchiveReader{ source: data, indexed: true, offset: 0, remaining: 1 }
 check(zip.next(&broken).failure.parse.kind == parse.Kind.Syntax)
 broken.source = data
 check(zip.next(&broken).failure.parse.kind == parse.Kind.Syntax)
 truncated := zip.open(data[..2])
 check(zip.next(&truncated).failure.parse.kind == parse.Kind.Syntax)
 truncated.source = data
 check(!zip.next(&truncated).found)
 header: [30]u8
 name: [64]u8
 payload: [64]u8
 for limit in 0..72 {
   input := Input{ source: data, fail: limit }
   stream := zip.stream_reader(io.Reader{ data: &input, read: read },header[..],name[..],payload[..])
   item := zip.next_stream(&stream)
   for item.found { item = zip.next_stream(&stream) }
   check(!item.found && item.failure.io.kind == errors.Kind.WouldBlock && item.failure.io.native == 0 && item.offset == limit)
   calls := input.calls
   again := zip.next_stream(&stream)
   check(again.failure.kind == item.failure.kind && again.offset == item.offset && again.failure.parse.kind == item.failure.parse.kind && input.calls == calls)
 }
 for limit in 0..36 {
   cursor := io.cursor(data[..limit])
   stream := zip.stream_reader(io.cursor_reader(&cursor),header[..],name[..],payload[..])
   item := zip.next_stream(&stream)
   if limit == 0 { check(!item.found && item.failure.kind == parse.StreamKind.Ok) }
   else { check(item.failure.parse.kind == parse.Kind.Syntax) }
   check(item.offset == limit && !item.found)
   again := zip.next_stream(&stream)
   check(again.failure.kind == item.failure.kind && again.failure.parse.kind == item.failure.parse.kind && again.offset == limit)
 }
 cursor := io.cursor(data[..36])
 stream := zip.stream_reader(io.cursor_reader(&cursor),header[..],name[..],payload[..])
 check(zip.next_stream(&stream).found)
 check(!zip.next_stream(&stream).found)
 native_input := Input{ source: data, fail: 32, native: -4 }
 native_stream := zip.stream_reader(io.Reader{ data: &native_input, read: read },header[..],name[..],payload[..])
 native_result := zip.next_stream(&native_stream)
 check(native_result.failure.io.kind == errors.Kind.WouldBlock && native_result.failure.io.native == -4 && native_result.offset == 32)
 check(zip.next_stream(&native_stream).failure.io.native == -4 && native_input.calls == 4)
 overlap := zip.stream_reader(io.Reader{},header[..],header[..],payload[..])
 check(zip.next_stream(&overlap).failure.parse.kind == parse.Kind.Overlap)
 capacity := zip.stream_reader(io.Reader{},header[..2],name[..],payload[..])
 check(zip.next_stream(&capacity).failure.parse.kind == parse.Kind.Capacity)
 invalid_open := zip.open_checked("x")
 check(invalid_open.failure.kind != parse.Kind.Ok && invalid_open.failure.kind == parse.Kind.Syntax)
 eof_input := Input{ source: "", fail: 100 }
 eof_stream := zip.stream_reader(io.Reader{ data: &eof_input, read: read },header[..],name[..],payload[..])
 eof := zip.next_stream(&eof_stream)
 check(!eof.found && eof.failure.kind == parse.StreamKind.Ok)
 check(!zip.next_stream(&eof_stream).found && eof_input.calls == 1)
 empty_checked := zip.open_checked(data[#len(data)-22..])
 check(empty_checked.failure.kind != parse.Kind.Ok)
 empty_eocd: [22]u8
 empty_eocd[0] = 80
 empty_eocd[1] = 75
 empty_eocd[2] = 5
 empty_eocd[3] = 6
 empty_archive := zip.open_checked(empty_eocd[..])
 check(empty_archive.failure.kind == parse.Kind.Ok && !zip.next(&empty_archive.value).found)
 empty_cursor := io.cursor(empty_eocd[..])
 empty_stream := zip.stream_reader(io.cursor_reader(&empty_cursor),header[..],name[..],payload[..])
 check(!zip.next_stream(&empty_stream).found && empty_stream.offset == 22)
 check(!zip.next_stream(&empty_stream).found && empty_stream.offset == 22)
 zero: zip.EntryResult
 zero_extract: zip.ExtractResult
 zero_open: zip.OpenResult
 check(!zero.found && zero.failure.kind == parse.StreamKind.Ok && zero.offset == 0 && zero.failure.kind == parse.StreamKind.Ok)
 check(zero_extract.failure.kind == parse.Kind.Ok && #len(zero_extract.value) == 0 && zero_open.failure.kind == parse.Kind.Ok)
 zero_reader: zip.ArchiveReader
 check(!zip.next(&zero_reader).found)
 overflow := zip.extract(arena,zip.Entry{ uncompressed_size: ~#cast(usize,0) })
 check(overflow.failure.kind != parse.Kind.Ok && overflow.failure.kind == parse.Kind.Overflow && mem.arena_used(arena) == mark)
}
'''

ARENA_SOURCE = r'''use "std/archive/zip" zip
use "std/mem" mem
fn main() {
 storage: [1+mem.ArenaBufferOverhead]u8
 pad := (16-(#cast(usize,&storage[0])&15))&15
 arena := mem.arena_from_buffer(storage[pad..pad+mem.ArenaHeader+1])
 _ = zip.extract(arena,zip.Entry{ payload: "hello", compressed_size: 5, uncompressed_size: 5 })
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
