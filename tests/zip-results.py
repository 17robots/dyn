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
use "std/errors" errors
use "std/io" io
use "std/mem" mem
use "std/bytes" bytes
fn check(ok: bool) { if !ok { #panic("zip fixture") } }
struct Input { source: []const u8, offset: usize, fail: usize, calls: usize, native: isize }
fn read(data: rawptr, destination: []u8) io.Result {
 s := #cast(*Input,data)
 s.calls += 1
 take := #len(destination)
 if take > s.fail - s.offset { take = s.fail - s.offset }
 if take > #len(s.source) - s.offset { take = #len(s.source) - s.offset }
 for i in 0..take { destination[i] = s.source[s.offset+i] }
 s.offset += take
 if s.offset == s.fail { return io.Result{ transferred: take, status: io.Status.Error, kind: errors.Kind.WouldBlock, error: s.native } }
 if s.offset == #len(s.source) { return io.Result{ transferred: take, status: io.Status.End } }
 return io.Result{ transferred: take }
}
fn main() {
 invalid_data: [46]u8 = [] invalid_data[0]=80 invalid_data[1]=75 invalid_data[2]=1 invalid_data[3]=2 invalid_data[42]=100
 invalid_state := zip.ArchiveReader{source:invalid_data[..],indexed:true,directory_start:200,directory_end:46,remaining:1}
 invalid := zip.next(&invalid_state)
 check(!invalid.ok && invalid.kind==errors.Kind.InvalidInput && invalid.error==0 && invalid.detail==zip.ErrorKind.Syntax && invalid_state.failed)
 invalid_state.source="" invalid_state.remaining=0
 replay_invalid:=zip.next(&invalid_state)
 check(!replay_invalid.ok && replay_invalid.kind==errors.Kind.InvalidInput && replay_invalid.detail==zip.ErrorKind.Syntax)
 data: []const u8 = DATA
 arena: mem.Arena
 state := zip.open(data)
 first := zip.next(&state)
 check(first.ok && first.kind == errors.Kind.None && first.error == 0 && first.offset == 36)
 decoded := zip.extract(&arena,first.value)
 check(decoded.ok && bytes.equal(decoded.value,"hello") && decoded.kind == errors.Kind.None)
 mark := mem.arena_used(&arena)
 bad := first.value
 bad.checksum = 0
 crc := zip.extract(&arena,bad)
 check(!crc.ok && crc.kind == errors.Kind.InvalidInput && crc.detail == zip.ErrorKind.Checksum && #len(crc.value) == 0 && mem.arena_used(&arena) == mark)
 empty := zip.next(&state)
 check(empty.ok && zip.extract(&arena,empty.value).ok)
 end := zip.next(&state)
 check(!end.ok && end.kind == errors.Kind.None && end.error == 0 && end.detail == zip.ErrorKind.End)
 opened := zip.open_checked(data)
 check(opened.ok)
 indexed := zip.next(&opened.value)
 check(indexed.ok && bytes.equal(indexed.value.payload,"hello"))
 check(zip.next(&opened.value).ok)
 check(zip.next(&opened.value).detail == zip.ErrorKind.End)
 broken := zip.ArchiveReader{ source: data, indexed: true, offset: 0, remaining: 1 }
 check(zip.next(&broken).kind == errors.Kind.InvalidInput)
 broken.source = data
 check(zip.next(&broken).detail == zip.ErrorKind.Syntax)
 truncated := zip.open(data[..2])
 check(zip.next(&truncated).kind == errors.Kind.InvalidInput)
 truncated.source = data
 check(!zip.next(&truncated).ok)
 header: [30]u8 = []
 name: [64]u8 = []
 payload: [64]u8 = []
 for limit in 0..72 {
   input := Input{ source: data, fail: limit }
   stream := zip.stream_reader(io.Reader{ data: &input, read: &read },header[..],name[..],payload[..])
   item := zip.next_stream(&stream)
   for item.ok { item = zip.next_stream(&stream) }
   check(!item.ok && item.kind == errors.Kind.WouldBlock && item.error == 0 && item.offset == limit)
   calls := input.calls
   again := zip.next_stream(&stream)
   check(again.kind == item.kind && again.offset == item.offset && again.detail == item.detail && input.calls == calls)
 }
 for limit in 0..36 {
   cursor := io.cursor(data[..limit])
   stream := zip.stream_reader(io.cursor_reader(&cursor),header[..],name[..],payload[..])
   item := zip.next_stream(&stream)
   if limit == 0 { check(item.kind == errors.Kind.None && item.detail == zip.ErrorKind.End) }
   else { check(item.kind == errors.Kind.InvalidInput && item.detail == zip.ErrorKind.Syntax) }
   check(item.offset == limit && !item.ok)
   again := zip.next_stream(&stream)
   check(again.kind == item.kind && again.detail == item.detail && again.offset == limit)
 }
 cursor := io.cursor(data[..36])
 stream := zip.stream_reader(io.cursor_reader(&cursor),header[..],name[..],payload[..])
 check(zip.next_stream(&stream).ok)
 check(zip.next_stream(&stream).detail == zip.ErrorKind.End)
 native_input := Input{ source: data, fail: 32, native: -4 }
 native_stream := zip.stream_reader(io.Reader{ data: &native_input, read: &read },header[..],name[..],payload[..])
 native_result := zip.next_stream(&native_stream)
 check(native_result.kind == errors.Kind.WouldBlock && native_result.error == -4 && native_result.offset == 32)
 check(zip.next_stream(&native_stream).error == -4 && native_input.calls == 4)
 overlap := zip.stream_reader(io.Reader{},header[..],header[..],payload[..])
 check(zip.next_stream(&overlap).detail == zip.ErrorKind.Overlap)
 capacity := zip.stream_reader(io.Reader{},header[..2],name[..],payload[..])
 check(zip.next_stream(&capacity).kind == errors.Kind.Capacity)
 invalid_open := zip.open_checked("x")
 check(!invalid_open.ok && invalid_open.kind == errors.Kind.InvalidInput && invalid_open.error == 0)
 eof_input := Input{ source: "", fail: 100 }
 eof_stream := zip.stream_reader(io.Reader{ data: &eof_input, read: &read },header[..],name[..],payload[..])
 eof := zip.next_stream(&eof_stream)
 check(!eof.ok && eof.kind == errors.Kind.None && eof.error == 0 && eof.detail == zip.ErrorKind.End)
 check(zip.next_stream(&eof_stream).detail == zip.ErrorKind.End && eof_input.calls == 1)
 empty_checked := zip.open_checked(data[#len(data)-22..])
 check(!empty_checked.ok)
 empty_eocd: [22]u8 = []
 empty_eocd[0] = 80
 empty_eocd[1] = 75
 empty_eocd[2] = 5
 empty_eocd[3] = 6
 empty_archive := zip.open_checked(empty_eocd[..])
 check(empty_archive.ok && zip.next(&empty_archive.value).detail == zip.ErrorKind.End)
 empty_cursor := io.cursor(empty_eocd[..])
 empty_stream := zip.stream_reader(io.cursor_reader(&empty_cursor),header[..],name[..],payload[..])
 check(zip.next_stream(&empty_stream).detail == zip.ErrorKind.End && empty_stream.offset == 22)
 check(zip.next_stream(&empty_stream).detail == zip.ErrorKind.End && empty_stream.offset == 22)
 zero: zip.EntryResult
 zero_extract: zip.ExtractResult
 zero_open: zip.OpenResult
 check(!zero.ok && zero.kind == errors.Kind.None && zero.error == 0 && zero.offset == 0 && zero.detail == zip.ErrorKind.None)
 check(!zero_extract.ok && #len(zero_extract.value) == 0 && !zero_open.ok)
 zero_reader: zip.ArchiveReader
 check(zip.next(&zero_reader).detail == zip.ErrorKind.End)
 overflow := zip.extract(&arena,zip.Entry{ uncompressed_size: ~#cast(usize,0) })
 check(!overflow.ok && overflow.kind == errors.Kind.Overflow && mem.arena_used(&arena) == mark)
}
'''

ARENA_SOURCE = r'''use "std/archive/zip" zip
use "std/mem" mem
fn main() {
 storage: [1]u8 = []
 arena := mem.arena_from_buffer(storage[..])
 _ = zip.extract(&arena,zip.Entry{ payload: "hello", compressed_size: 5, uncompressed_size: 5 })
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
                assert result.returncode != 0 and "arena exhausted" in result.stderr, (
                    name, mode, result.returncode, result.stdout, result.stderr)
            else:
                assert result.returncode == 0, (name, mode, result.stdout, result.stderr)
print("PASS ZIP results, EOF, sticky errors, CRC rollback and arena panic (debug/release)")
