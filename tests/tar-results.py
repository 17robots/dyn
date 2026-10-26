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
use "std/errors" errors
use "std/io" io
use "std/bytes" bytes
fn check(ok: bool) { if !ok { #panic("tar fixture") } }
struct Input { source: []const u8, offset: usize, fail: usize, calls: usize, native: isize }
fn read(data: rawptr, destination: []u8) io.Result {
 s := #cast(*Input,data)
 s.calls += 1
 take := #len(destination)
 if take > s.fail - s.offset { take = s.fail - s.offset }
 if take > #len(s.source) - s.offset { take = #len(s.source) - s.offset }
 for i in 0..take { destination[i] = s.source[s.offset+i] }
 s.offset += take
 if s.offset == s.fail { return io.Result{ transferred: take, status: io.Status.Error, kind: errors.Kind.PermissionDenied, error: s.native } }
 if s.offset == #len(s.source) { return io.Result{ transferred: take, status: io.Status.End } }
 return io.Result{ transferred: take }
}
fn replay(state: *tar.StreamReader, input: *Input, native: isize, offset: usize) {
 calls := input.calls
 again := tar.next_stream(state)
 check(!again.ok && again.kind == errors.Kind.PermissionDenied && again.error == native && again.offset == offset)
 storage: [8]u8 = []
 for count in [0, 8] {
   result := tar.read_stream(state, storage[..count])
   check(result.status == io.Status.Error && result.kind == errors.Kind.PermissionDenied && result.error == native)
 }
 check(input.calls == calls)
}
fn main() {
 data: []const u8 = DATA
 for archive in [data, PAX, GNU] {
   state := tar.reader(archive)
   first := tar.next(&state)
   check(first.status == tar.Status.Entry && first.kind == errors.Kind.None && first.error == 0 && first.detail == tar.ErrorKind.None)
   check(bytes.equal(first.entry.data,"hello") && first.entry.kind == '0')
   empty := tar.next(&state)
   check(empty.status == tar.Status.Entry && #len(empty.entry.data) == 0)
   end := tar.next(&state)
   check(end.status == tar.Status.End && end.kind == errors.Kind.None && end.error == 0)
   check(tar.next(&state).status == tar.Status.End)
   header: [512]u8 = []
   metadata: [2048]u8 = []
   cursor := io.cursor(archive)
   stream := tar.stream_reader(io.cursor_reader(&cursor),header[..],metadata[..])
   item := tar.next_stream(&stream)
   check(item.ok && item.kind == errors.Kind.None && item.error == 0 && item.typeflag == '0' && item.size == 5)
   check(bytes.equal(item.name,first.entry.name))
   payload: [8]u8 = []
   loaded := tar.read_stream(&stream,payload[..])
   check(loaded.status == io.Status.End && loaded.transferred == 5 && bytes.equal(payload[..5],"hello"))
   check(tar.read_stream(&stream,payload[..]).status == io.Status.End)
   check(tar.next_stream(&stream).ok)
   check(tar.read_stream(&stream,payload[..]).status == io.Status.End)
   check(!tar.next_stream(&stream).ok && stream.ended && !stream.failed)
 }
 // Physical EOF exactly at a record boundary remains normal exhaustion.
 for source in ["", data[..1536]] {
   state := tar.reader(source)
   result := tar.next(&state)
   for result.status == tar.Status.Entry { result = tar.next(&state) }
   check(result.status == tar.Status.End && result.kind == errors.Kind.None)
   header: [512]u8 = []
   cursor := io.cursor(source)
   stream := tar.stream_reader(io.cursor_reader(&cursor),header[..],header[..0])
   item := tar.next_stream(&stream)
   for item.ok { item = tar.next_stream(&stream) }
   check(item.kind == errors.Kind.None && item.error == 0 && item.offset == #len(source))
   check(tar.next_stream(&stream).offset == item.offset)
 }
 // Native zero is an error, even when a callback fills the requested slice.
 for native in [#cast(isize,0), #cast(isize,-13)] {
   for raw_limit in [0, 1, 511, 512, 514, 517, 518, 1023, 1024, 1536] {
   limit := #cast(usize,raw_limit)
     input := Input{ source: data, fail: limit, native: native }
     header: [512]u8 = []
     stream := tar.stream_reader(io.Reader{ data: &input, read: read },header[..],header[..0])
     item := tar.next_stream(&stream)
     for item.ok { item = tar.next_stream(&stream) }
     check(item.kind == errors.Kind.PermissionDenied && item.error == native && item.offset == limit)
     replay(&stream,&input,native,limit)
   }
   for raw_limit in [512, 513, 517] {
   limit := #cast(usize,raw_limit)
     input := Input{ source: data, fail: limit, native: native }
     header: [512]u8 = []
     stream := tar.stream_reader(io.Reader{ data: &input, read: read },header[..],header[..0])
     item := tar.next_stream(&stream)
     if item.ok {
       destination: [8]u8 = []
       loaded := tar.read_stream(&stream,destination[..])
       check(loaded.status == io.Status.Error && loaded.kind == errors.Kind.PermissionDenied && loaded.error == native && loaded.transferred == limit - 512)
     }
     replay(&stream,&input,native,limit)
   }
   // Fail in extension headers, payload, padding, and the following header.
   for raw_limit in [0, 512, 513, 700, 1024, 1025] {
   limit := #cast(usize,raw_limit)
     input := Input{ source: PAX, fail: limit, native: native }
     header: [512]u8 = []
     metadata: [2048]u8 = []
     stream := tar.stream_reader(io.Reader{ data: &input, read: read },header[..],metadata[..])
     item := tar.next_stream(&stream)
     check(!item.ok && item.kind == errors.Kind.PermissionDenied && item.error == native && item.offset == limit)
     replay(&stream,&input,native,limit)
   }
 }
 // Partial header, payload, and padding EOF report the first missing byte.
 for raw_length in [1, 511, 512, 514, 517, 518, 1023] {
   length := #cast(usize,raw_length)
   state := tar.reader(data[..length])
   failed := tar.next(&state)
   check(failed.status == tar.Status.Error && failed.kind == errors.Kind.InvalidInput && failed.error == 0 && failed.detail == tar.ErrorKind.Truncated && failed.offset == length && state.offset == 0)
   header: [512]u8 = []
   cursor := io.cursor(data[..length])
   stream := tar.stream_reader(io.cursor_reader(&cursor),header[..],header[..0])
   item := tar.next_stream(&stream)
   for item.ok { item = tar.next_stream(&stream) }
   check(item.kind == errors.Kind.InvalidInput && item.error == 0 && item.detail == tar.ErrorKind.Truncated && item.offset == length)
   check(tar.next_stream(&stream).offset == length)
 }
 bad_header: [512]u8 = []
 for i in 0..512 { bad_header[i] = data[i] }
 bad_header[0] = '!'
 bad := tar.reader(bad_header[..])
 result := tar.next(&bad)
 check(result.status == tar.Status.Error && result.kind == errors.Kind.InvalidInput && result.error == 0 && result.detail == tar.ErrorKind.Header && result.offset == 0 && bad.offset == 0)
 invalid := tar.ArchiveReader{ source: data, offset: #len(data)+1 }
 invalid_result := tar.next(&invalid)
 check(invalid_result.detail == tar.ErrorKind.InvalidOffset && invalid_result.kind == errors.Kind.InvalidInput && invalid_result.error == 0 && invalid_result.offset == #len(data)+1)
 checksum_input := Input{ source: bad_header[..], fail: 9999 }
 checksum_storage: [512]u8 = []
 checksum_stream := tar.stream_reader(io.Reader{ data: &checksum_input, read: read },checksum_storage[..],checksum_storage[..0])
 checksum_result := tar.next_stream(&checksum_stream)
 check(!checksum_result.ok && checksum_result.kind == errors.Kind.InvalidInput && checksum_result.error == 0 && checksum_result.detail == tar.ErrorKind.Header && checksum_result.offset == 512)
 checksum_calls := checksum_input.calls
 check(tar.next_stream(&checksum_stream).offset == 512)
 check(tar.read_stream(&checksum_stream,checksum_storage[..0]).kind == errors.Kind.InvalidInput && checksum_input.calls == checksum_calls)
 // A global PAX prefix followed by a damaged header commits neither cursor nor defaults.
 dirty := tar.reader(DIRTY)
 prefix_error := tar.next(&dirty)
 check(prefix_error.status == tar.Status.Error && prefix_error.kind == errors.Kind.InvalidInput && prefix_error.detail == tar.ErrorKind.Header && prefix_error.offset == 1024 && dirty.offset == 0)
 check(tar.next(&dirty).offset == prefix_error.offset)
 dirty.source = data
 check(bytes.equal(tar.next(&dirty).entry.name,"a"))
 zero: tar.ArchiveReader
 check(tar.next(&zero).status == tar.Status.End)
 zero_stream: tar.StreamReader
 check(tar.next_stream(&zero_stream).kind == errors.Kind.Capacity)
 check(tar.read_stream(&zero_stream,bad_header[..0]).kind == errors.Kind.Capacity)
 no_entry: tar.StreamReader
 check(tar.read_stream(&no_entry,bad_header[..0]).kind == errors.Kind.InvalidState)
 check(tar.next_stream(&no_entry).kind == errors.Kind.InvalidState)
 overlap := tar.stream_reader(io.Reader{},bad_header[..],bad_header[..])
 check(tar.next_stream(&overlap).detail == tar.ErrorKind.Overlap)
 check(tar.read_stream(&overlap,bad_header[..0]).kind == errors.Kind.InvalidInput)
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
