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


SOURCE = r'''use "std/archive/tar" tar
use "std/fail"
use "std/io" io
use "std/bytes" bytes
fn check(ok: bool) { if !ok { #panic("tar fixture") } }
struct Input { source: []const u8, offset: usize, fail: usize, calls: usize, native: isize }
fn read(data: rawptr, status: *fail.Status, destination: []u8) usize {
 s := #cast(*Input,data)
 s.calls += 1
 if s.offset == s.fail {
  failure := fail.make(fail.Kind.PermissionDenied, "read", "", "denied")
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
struct Streamed { entry: tar.StreamEntry, failure: fail.Failure }
fn stream_next(state: *tar.StreamReader) Streamed {
 status: fail.Status
 entry := tar.next_stream(&status, state)
 return Streamed{ entry: entry, failure: status.failure }
}
fn read_failure(state: *tar.StreamReader, destination: []u8) fail.Failure {
 status: fail.Status
 count := tar.read_stream(&status, state, destination)
 check(status.failed && count == 0)
 return status.failure
}
struct Found { next: tar.Next, failure: fail.Failure }
fn next(state: *tar.ArchiveReader) Found {
 status: fail.Status
 found := tar.next(&status, state)
 return Found{ next: found, failure: status.failure }
}
fn replay(state: *tar.StreamReader, input: *Input, native: isize, offset: usize) {
 calls := input.calls
 again := stream_next(state)
 check(!again.entry.found && again.failure.kind == fail.Kind.PermissionDenied && again.failure.native == native && again.entry.offset == offset)
 storage: [8]u8
 for count in [0, 8] {
   failure := read_failure(state, storage[..count])
   check(failure.kind == fail.Kind.PermissionDenied && failure.native == native)
 }
 check(input.calls == calls)
}
fn main() {
 status := fail.Status{ on_failure: fail.panic_on_failure }
 data: []const u8 = DATA
 for archive in [data, PAX, GNU] {
   state := tar.reader(archive)
   first := tar.next(&status, &state)
   check(first.found)
   check(bytes.equal(first.entry.data,"hello") && first.entry.kind == '0')
   empty := tar.next(&status, &state)
   check(empty.found && #len(empty.entry.data) == 0)
   end := tar.next(&status, &state)
   check(!end.found)
   check(!tar.next(&status, &state).found)
   header: [512]u8
   metadata: [2048]u8
   cursor := io.cursor(archive)
   stream := tar.stream_reader(io.cursor_reader(&cursor),header[..],metadata[..])
   item := tar.next_stream(&status, &stream)
   check(item.found && item.typeflag == '0' && item.size == 5)
   check(bytes.equal(item.name,first.entry.name))
   payload: [8]u8
   loaded := tar.read_stream(&status, &stream,payload[..])
   check(loaded == 5 && bytes.equal(payload[..5],"hello"))
   check(tar.read_stream(&status, &stream,payload[..]) == 0)
   check(tar.next_stream(&status, &stream).found)
   check(tar.read_stream(&status, &stream,payload[..]) == 0)
   check(!tar.next_stream(&status, &stream).found && stream.ended && !stream.failed)
 }
 // Physical EOF exactly at a record boundary remains normal exhaustion.
 for source in ["", data[..1536]] {
   state := tar.reader(source)
   result := tar.next(&status, &state)
   for result.found { result = tar.next(&status, &state) }
   header: [512]u8
   cursor := io.cursor(source)
   stream := tar.stream_reader(io.cursor_reader(&cursor),header[..],header[..0])
   item := tar.next_stream(&status, &stream)
   for item.found { item = tar.next_stream(&status, &stream) }
   check(item.offset == #len(source))
   check(tar.next_stream(&status, &stream).offset == item.offset)
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
     check(item.failure.kind == fail.Kind.PermissionDenied && item.failure.native == native && item.entry.offset == limit)
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
       reading: fail.Status
       for !reading.failed && tar.read_stream(&reading, &stream, destination[..]) != 0 {}
       if !reading.failed {
         reading.failure = stream_next(&stream).failure
       }
       check(reading.failure.kind == fail.Kind.PermissionDenied && reading.failure.native == native && stream.offset == limit)
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
     check(!item.entry.found && item.failure.kind == fail.Kind.PermissionDenied && item.failure.native == native && item.entry.offset == limit)
     replay(&stream,&input,native,limit)
   }
 }
 // Partial header, payload, and padding EOF report the first missing byte.
 for raw_length in [1, 511, 512, 514, 517, 518, 1023] {
   length := #cast(usize,raw_length)
   state := tar.reader(data[..length])
   failed := next(&state)
   check(failed.failure.kind == fail.Kind.InvalidInput && failed.failure.offset == length && state.offset == 0)
   header: [512]u8
   cursor := io.cursor(data[..length])
   stream := tar.stream_reader(io.cursor_reader(&cursor),header[..],header[..0])
   item := stream_next(&stream)
   for item.entry.found { item = stream_next(&stream) }
   check(item.failure.kind == fail.Kind.InvalidInput && item.entry.offset == length)
   check(stream_next(&stream).entry.offset == length)
 }
 bad_header: [512]u8
 for i in 0..512 { bad_header[i] = data[i] }
 bad_header[0] = '!'
 bad := tar.reader(bad_header[..])
 result := next(&bad)
 check(result.failure.kind == fail.Kind.InvalidInput && result.failure.offset == 0 && bad.offset == 0)
 invalid := tar.ArchiveReader{ source: data, offset: #len(data)+1 }
 invalid_result := next(&invalid)
 check(invalid_result.failure.kind == fail.Kind.InvalidInput && invalid_result.failure.offset == #len(data)+1)
 checksum_input := Input{ source: bad_header[..], fail: 9999 }
 checksum_storage: [512]u8
 checksum_stream := tar.stream_reader(io.Reader{ data: &checksum_input, read: read },checksum_storage[..],checksum_storage[..0])
 checksum_result := stream_next(&checksum_stream)
 check(!checksum_result.entry.found && checksum_result.failure.kind == fail.Kind.InvalidInput && checksum_result.entry.offset == 512)
 checksum_calls := checksum_input.calls
 check(stream_next(&checksum_stream).entry.offset == 512)
 check(read_failure(&checksum_stream,checksum_storage[..0]).kind == fail.Kind.InvalidInput && checksum_input.calls == checksum_calls)
 // A global PAX prefix followed by a damaged header commits neither cursor nor defaults.
 dirty := tar.reader(DIRTY)
 prefix_error := next(&dirty)
 check(prefix_error.failure.kind == fail.Kind.InvalidInput && prefix_error.failure.offset == 1024 && dirty.offset == 0)
 check(next(&dirty).failure.offset == prefix_error.failure.offset)
 dirty.source = data
 check(bytes.equal(tar.next(&status, &dirty).entry.name,"a"))
 zero: tar.ArchiveReader
 check(!tar.next(&status, &zero).found)
 zero_stream: tar.StreamReader
 check(stream_next(&zero_stream).failure.kind == fail.Kind.Capacity)
 check(read_failure(&zero_stream,bad_header[..0]).kind == fail.Kind.Capacity)
 no_entry: tar.StreamReader
 check(read_failure(&no_entry,bad_header[..0]).kind == fail.Kind.InvalidState)
 overlap := tar.stream_reader(io.Reader{},bad_header[..],bad_header[..])
 check(stream_next(&overlap).failure.kind == fail.Kind.InvalidInput)
 check(read_failure(&overlap,bad_header[..0]).kind == fail.Kind.InvalidInput)
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
