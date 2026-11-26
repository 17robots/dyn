#!/usr/bin/env python3
"""Independent Python TAR goldens and portable/sticky TAR result contracts."""
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get("DYN", ROOT / "build/dyn-release")).resolve())


def golden(format, name="a", global_headers=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=format,
                      pax_headers=global_headers) as archive:
        for entry_name, payload in ((name, b"hello"), ("empty", b"")):
            entry = tarfile.TarInfo(entry_name)
            entry.size = len(payload)
            entry.mtime = 0
            archive.addfile(entry, io.BytesIO(payload))
    return output.getvalue()


def literal(data):
    return '"' + "".join(f"\\x{byte:02x}" for byte in data) + '"'


SOURCE = r'''use tar "std/archive/tar"
use io "std/io"
use bytes "std/bytes"
use parse "std/parse"
fn check(ok: bool) { if !ok { #panic("tar fixture") } }
struct Input { source: []const u8, offset: usize, fail: usize, calls: usize, native: isize }
fn read(data: rawptr, destination: []u8) usize!io.IoErr {
 s := #cast(*Input,data)
 s.calls += 1
 if s.offset == s.fail { fail .PermissionDenied }
 take := destination.len
 if take > s.fail - s.offset { take = s.fail - s.offset }
 if take > s.source.len - s.offset { take = s.source.len - s.offset }
 for i in 0..take { destination[i] = s.source[s.offset+i] }
 s.offset += take
 return take
}
// The kinds of failure these fixtures meet; Ok when a call worked.
enum Kind { Ok, InvalidInput, PermissionDenied, Capacity, Other }
fn kind_of(err: io.IoErr) Kind {
 case err {
  .InvalidInput => { return Kind.InvalidInput }
  .PermissionDenied => { return Kind.PermissionDenied }
  .Capacity => { return Kind.Capacity }
  _ => { return Kind.Other }
 }
}
// The entry a call returned, whether it returned one (the reader's ended,
// inverted), and for archives the reader's offset after the call.
struct Item { name: []const u8, prefix: []const u8, link_name: []const u8, size: u64, typeflag: u8, offset: usize, found: bool }
fn item_next(state: *tar.StreamReader) Item {
 entry := tar.next_stream(state) catch { #panic("tar next_stream") }
 return Item{ name: entry.name, prefix: entry.prefix, link_name: entry.link_name, size: entry.size, typeflag: entry.typeflag, offset: entry.offset, found: !state.ended }
}
struct Next { entry: tar.Entry, offset: usize, found: bool }
fn entry_next(state: *tar.ArchiveReader) Next {
 entry := tar.next(state) catch { #panic("tar next") }
 return Next{ entry: entry, offset: state.offset, found: !state.ended }
}
struct Streamed { entry: Item, failure: Kind }
fn stream_next(state: *tar.StreamReader) Streamed {
 entry := tar.next_stream(state) catch err {
  return Streamed{ entry: Item{ offset: state.offset }, failure: kind_of(err) }
 }
 return Streamed{ entry: Item{ name: entry.name, prefix: entry.prefix, link_name: entry.link_name, size: entry.size, typeflag: entry.typeflag, offset: entry.offset, found: !state.ended } }
}
fn read_failure(state: *tar.StreamReader, destination: []u8) Kind {
 _ = tar.read_stream(state, destination) catch err { return kind_of(err) }
 #panic("read_stream should fail")
}
// What next found, or the failure and its offset.
struct Found { next: Next, failure: Kind, offset: usize }
fn next(state: *tar.ArchiveReader) Found {
 entry := tar.next(state) catch err {
  return Found{ failure: Kind.InvalidInput, offset: parse.offset(err) }
 }
 return Found{ next: Next{ entry: entry, offset: state.offset, found: !state.ended } }
}
fn replay(state: *tar.StreamReader, input: *Input, native: isize, offset: usize) {
 calls := input.calls
 again := stream_next(state)
 check(!again.entry.found && again.failure == Kind.PermissionDenied && again.entry.offset == offset)
 storage: [8]u8
 for count in [0, 8] {
   check(read_failure(state, storage[..count]) == Kind.PermissionDenied)
 }
 check(input.calls == calls)
}
// Reads the entry to its end; Ok, or the kind of the failure that stopped it.
fn read_until_failure(state: *tar.StreamReader, destination: []u8) Kind {
 for {
  count := tar.read_stream(state, destination) catch err { return kind_of(err) }
  if count == 0 { return Kind.Ok }
 }
}
fn main() {
 data: []const u8 = DATA
 for archive in [data, PAX, GNU] {
   state := tar.reader(archive)
   first := entry_next(&state)
   check(first.found)
   check(bytes.equal(first.entry.data,"hello") && first.entry.kind == '0')
   empty := entry_next(&state)
   check(empty.found && empty.entry.data.len == 0)
   end := entry_next(&state)
   check(!end.found)
   check(!entry_next(&state).found)
   header: [512]u8
   metadata: [2048]u8
   cursor := io.cursor(archive)
   stream := tar.stream_reader(io.cursor_reader(&cursor),header[..],metadata[..])
   item := item_next(&stream)
   check(item.found && item.typeflag == '0' && item.size == 5)
   check(bytes.equal(item.name,first.entry.name))
   payload: [8]u8
   loaded := tar.read_stream(&stream,payload[..]) catch { #panic("read_stream") }
   check(loaded == 5 && bytes.equal(payload[..5],"hello"))
   check((tar.read_stream(&stream,payload[..]) catch 99) == 0)
   check(item_next(&stream).found)
   check((tar.read_stream(&stream,payload[..]) catch 99) == 0)
   check(!item_next(&stream).found && stream.ended && !stream.failed)
 }
 // Physical EOF exactly at a record boundary remains normal exhaustion.
 for source in ["", data[..1536]] {
   state := tar.reader(source)
   result := entry_next(&state)
   for result.found { result = entry_next(&state) }
   header: [512]u8
   cursor := io.cursor(source)
   stream := tar.stream_reader(io.cursor_reader(&cursor),header[..],header[..0])
   item := item_next(&stream)
   for item.found { item = item_next(&stream) }
   check(item.offset == source.len)
   check(item_next(&stream).offset == item.offset)
 }
 // A reader failure stays on the stream, with its native code, even zero.
 for native in [#cast(isize,0), #cast(isize,-13)] {
   for raw_limit in [0, 1, 511, 512, 514, 517, 518, 1023, 1024, 1536] {
   limit := #cast(usize,raw_limit)
     input := Input{ source: data, fail: limit, native: native }
     header: [512]u8
     stream := tar.stream_reader(io.Reader{ data: &input, read: read },header[..],header[..0])
     item := stream_next(&stream)
     for item.entry.found { item = stream_next(&stream) }
     check(item.failure == Kind.PermissionDenied && item.entry.offset == limit)
     replay(&stream,&input,native,limit)
   }
   for raw_limit in [512, 513, 517] {
   limit := #cast(usize,raw_limit)
     input := Input{ source: data, fail: limit, native: native }
     header: [512]u8
     stream := tar.stream_reader(io.Reader{ data: &input, read: read },header[..],header[..0])
     item := stream_next(&stream)
     if item.entry.found {
       // The payload may arrive whole before the reader fails; then the
       // next header read meets the failure.
       destination: [8]u8
       reading := read_until_failure(&stream, destination[..])
       if reading == Kind.Ok {
         reading = stream_next(&stream).failure
       }
       check(reading == Kind.PermissionDenied && stream.offset == limit)
     }
     replay(&stream,&input,native,limit)
   }
   // Fail in extension headers, payload, padding, and the following header.
   for raw_limit in [0, 512, 513, 700, 1024, 1025] {
   limit := #cast(usize,raw_limit)
     input := Input{ source: PAX, fail: limit, native: native }
     header: [512]u8
     metadata: [2048]u8
     stream := tar.stream_reader(io.Reader{ data: &input, read: read },header[..],metadata[..])
     item := stream_next(&stream)
     check(!item.entry.found && item.failure == Kind.PermissionDenied && item.entry.offset == limit)
     replay(&stream,&input,native,limit)
   }
 }
 // Partial header, payload, and padding EOF report the first missing byte.
 for raw_length in [1, 511, 512, 514, 517, 518, 1023] {
   length := #cast(usize,raw_length)
   state := tar.reader(data[..length])
   failed := next(&state)
   check(failed.failure == Kind.InvalidInput && failed.offset == length && state.offset == 0)
   header: [512]u8
   cursor := io.cursor(data[..length])
   stream := tar.stream_reader(io.cursor_reader(&cursor),header[..],header[..0])
   item := stream_next(&stream)
   for item.entry.found { item = stream_next(&stream) }
   check(item.failure == Kind.InvalidInput && item.entry.offset == length)
   check(stream_next(&stream).entry.offset == length)
 }
 bad_header: [512]u8
 for i in 0..512 { bad_header[i] = data[i] }
 bad_header[0] = '!'
 bad := tar.reader(bad_header[..])
 result := next(&bad)
 check(result.failure == Kind.InvalidInput && result.offset == 0 && bad.offset == 0)
 invalid := tar.ArchiveReader{ source: data, offset: data.len+1 }
 invalid_result := next(&invalid)
 check(invalid_result.failure == Kind.InvalidInput && invalid_result.offset == data.len+1)
 checksum_input := Input{ source: bad_header[..], fail: 9999 }
 checksum_storage: [512]u8
 checksum_stream := tar.stream_reader(io.Reader{ data: &checksum_input, read: read },checksum_storage[..],checksum_storage[..0])
 checksum_result := stream_next(&checksum_stream)
 check(!checksum_result.entry.found && checksum_result.failure == Kind.InvalidInput && checksum_result.entry.offset == 512)
 checksum_calls := checksum_input.calls
 check(stream_next(&checksum_stream).entry.offset == 512)
 check(read_failure(&checksum_stream,checksum_storage[..0]) == Kind.InvalidInput && checksum_input.calls == checksum_calls)
 // A global PAX prefix followed by a damaged header commits neither cursor nor defaults.
 dirty := tar.reader(DIRTY)
 prefix_error := next(&dirty)
 check(prefix_error.failure == Kind.InvalidInput && prefix_error.offset == 1024 && dirty.offset == 0)
 check(next(&dirty).offset == prefix_error.offset)
 dirty.source = data
 check(bytes.equal(entry_next(&dirty).entry.name,"a"))
 zero: tar.ArchiveReader
 check(!entry_next(&zero).found)
 zero_stream: tar.StreamReader
 check(stream_next(&zero_stream).failure == Kind.Capacity)
 check(read_failure(&zero_stream,bad_header[..0]) == Kind.Capacity)
 no_entry: tar.StreamReader
 check(read_failure(&no_entry,bad_header[..0]) == Kind.InvalidInput)
 overlap := tar.stream_reader(io.Reader{},bad_header[..],bad_header[..])
 check(stream_next(&overlap).failure == Kind.InvalidInput)
 check(read_failure(&overlap,bad_header[..0]) == Kind.InvalidInput)
}
'''

plain = golden(tarfile.USTAR_FORMAT)
pax = golden(tarfile.PAX_FORMAT, "long/" + "x" * 110)
gnu = golden(tarfile.GNU_FORMAT, "long/" + "x" * 110)
dirty = bytearray(golden(tarfile.PAX_FORMAT, global_headers={"path": "global-name"}))
dirty[1024] ^= 1
for name, data in (("DATA", plain), ("PAX", pax), ("GNU", gnu), ("DIRTY", dirty)):
    SOURCE = SOURCE.replace(name, literal(data))

with tempfile.TemporaryDirectory(prefix="dyn-tar-results-") as temporary:
    project = Path(temporary)
    (project / "main.dyn").write_text(SOURCE, encoding="utf-8")
    output = project / ("program.exe" if os.name == "nt" else "program")
    for mode in ("--debug", "--release"):
        subprocess.run([DYN, "build", str(project), "--no-cache", "--quiet", mode,
                        "--output", str(output)], check=True, timeout=90)
        result = subprocess.run([str(output)], capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, (mode, result.stdout, result.stderr)
        print("PASS TAR portable results, Python goldens, offsets, sticky errors " + mode, flush=True)
