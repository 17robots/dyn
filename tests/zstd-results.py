#!/usr/bin/env python3
"""Independent native zstd fixtures and std portable-result regression checks."""
import ctypes as c
import ctypes.util
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
if not DYN.is_file():
    print('SKIP zstd-results: compiler unavailable:', DYN)
    raise SystemExit(0)
try:
    lib = c.CDLL(ctypes.util.find_library('zstd') or 'libzstd.so')
    for name, args, result in [
        ('ZSTD_compressBound', [c.c_size_t], c.c_size_t),
        ('ZSTD_compress', [c.c_void_p, c.c_size_t, c.c_void_p, c.c_size_t, c.c_int], c.c_size_t),
        ('ZSTD_isError', [c.c_size_t], c.c_uint),
        ('ZSTD_createCCtx', [], c.c_void_p),
        ('ZSTD_freeCCtx', [c.c_void_p], c.c_size_t),
        ('ZSTD_CCtx_setParameter', [c.c_void_p, c.c_int, c.c_int], c.c_size_t),
        ('ZSTD_compress2', [c.c_void_p, c.c_void_p, c.c_size_t, c.c_void_p, c.c_size_t], c.c_size_t),
    ]:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, result
except (OSError, AttributeError) as exc:
    print('SKIP zstd-results: native zstd prerequisite:', exc)
    raise SystemExit(0)

SOURCE = '''use z "std/compress/zstd"
use io "std/io"
use mem "std/mem"
use "std/fail"
use fs "std/fs"
use bytes "std/bytes"
struct Input { source: []const u8, at: usize, chunk: usize }
fn read(data: rawptr, destination: []u8) usize!io.IoErr {
  status: fail.Status
  count := read_status(data, &status, destination)
  try io.check_status(&status)
  return count
}
fn read_status(data: rawptr, status: *fail.Status, destination: []u8) usize {
 state := #cast(*Input, data)
 amount := state.source.len - state.at
 if amount > state.chunk { amount = state.chunk }
 if amount > destination.len { amount = destination.len }
 _ = mem.copy(destination[..amount], state.source[state.at..state.at + amount])
 state.at += amount
 return amount
}
fn verify(raw: []const u8, encoded: []const u8, workspace: []u8, chunk: usize, window: u32, bad: bool, repeats: usize) {
 input := Input{ source: encoded, chunk: chunk }
 compressed: [113]u8
 output: [8191]u8
 state := z.decoder(io.Reader{ data: #cast(rawptr, &input), read: read }, compressed[..], workspace, window)
 reader := z.decoder_reader(&state)
 total: usize = 0
 for {
  status: fail.Status
  count := io.read_status(&status, reader, output[..])
  if status.failed {
   if !bad { #panic("zstd unexpected error") }
   again: fail.Status
   _ = io.read_status(&again, reader, output[..])
   if again.failure.native != status.failure.native || again.failure.kind != status.failure.kind { #panic("zstd sticky error") }
   return
  }
  at: usize = 0
  for at < count {
   if total >= raw.len * repeats || output[at] != raw[total % raw.len] { #panic("zstd output") }
   total += 1
   at += 1
  }
  if count == 0 {
   if bad || total != raw.len * repeats { #panic("zstd completion") }
   end: fail.Status
   if io.read_status(&end, reader, output[..]) != 0 || end.failed { #panic("zstd sticky end") }
   return
  }
 }
}
'''
source = SOURCE
extra = '''
struct Upstream { calls: usize, code: isize }
fn refuse(data: rawptr, destination: []u8) usize!io.IoErr {
  status: fail.Status
  count := refuse_status(data, &status, destination)
  try io.check_status(&status)
  return count
}
fn refuse_status(data: rawptr, status: *fail.Status, destination: []u8) usize {
 state := #cast(*Upstream, data)
 state.calls += 1
 failure := fail.make(fail.Kind.PermissionDenied, "read", "", "refused")
 failure.native = state.code
 fail.set(status, failure)
 return 0
}
fn results(arena: *mem.Arena, encoded: []const u8, unknown: []const u8, workspace: []u8) {
 status := fail.Status{ on_failure: fail.panic_on_failure }
 squeezed := z.compress(arena, &status, "portable zstd", 3)
 unpacked := z.decompress(arena, &status, squeezed)
 if unpacked.len != 13 { #panic("roundtrip") }
 mark := mem.arena_used(arena)
 bad: fail.Status
 bad_value := z.decompress(arena, &bad, "bad")
 if bad.failure.kind != fail.Kind.InvalidInput || bad_value.len != 0 || mem.arena_used(arena) != mark { #panic("malformed result") }
 size := z.frame_size(&status, unknown)
 if size.known { #panic("unknown valid frame") }
 unsupported: fail.Status
 _ = z.decompress(arena, &unsupported, unknown)
 if unsupported.failure.kind != fail.Kind.Unsupported || mem.arena_used(arena) != mark { #panic("unknown arena unsupported") }
 // Header retains a valid known size, while truncation fails after allocation.
 broken: fail.Status
 broken_value := z.decompress(arena, &broken, encoded[..encoded.len-1])
 if broken.failure.kind != fail.Kind.InvalidInput || broken.failure.native == 0 || broken_value.len != 0 || mem.arena_used(arena) != mark { #panic("provider rollback") }
 code: isize = 0
 for code < 2 {
  upstream := Upstream{ code: code }
  compressed: [17]u8
  output: [11]u8
  state := z.decoder(io.Reader{ data: &upstream, read: refuse }, compressed[..], workspace, 21)
  reader := z.decoder_reader(&state)
  first: fail.Status
  _ = io.read_status(&first, reader, output[..])
  replay: fail.Status
  direct(&replay, reader, output[..0])
  if !first.failed || first.failure.kind != fail.Kind.PermissionDenied || !replay.failed || replay.failure.kind != first.failure.kind || upstream.calls != 1 { #panic("sticky upstream native zero / empty callback") }
  code += 1
 }
 compressed: [17]u8
 output: [11]u8
 input := Input{ source: "bad", chunk: 3 }
 state := z.decoder(io.Reader{ data: &input, read: read }, compressed[..], workspace, 21)
 reader := z.decoder_reader(&state)
 failed: fail.Status
 _ = io.read_status(&failed, reader, output[..])
 replay: fail.Status
 direct(&replay, reader, output[..0])
 if !failed.failed || failed.failure.kind != fail.Kind.InvalidInput || replay.failure.kind != failed.failure.kind || !replay.failed { #panic("sticky provider diagnostic") }
}
'''
source = source + extra + r'''
// Calls the adapter itself, even for an empty destination, which io.read
// would not pass on.
fn direct(status: *fail.Status, reader: io.Reader, destination: []u8) {
 _ = reader.read(reader.data, destination) catch err {
  fail.set(status, io.failure_of(err, "read", ""))
  return
 }
}
fn main() {
 invalid := z.Decoder{offset:1}
 adapter := z.decoder_reader(&invalid)
 destination: [1]u8
 failed_invalid: fail.Status
 _ = io.read_status(&failed_invalid, adapter, destination[..])
 if !failed_invalid.failed || failed_invalid.failure.kind != fail.Kind.InvalidInput || !invalid.failed { #panic("invalid decoder cursor") }
 invalid.offset=0
 replay_invalid: fail.Status
 direct(&replay_invalid, adapter, destination[..0])
 if !replay_invalid.failed || replay_invalid.failure.kind != fail.Kind.InvalidInput { #panic("sticky invalid decoder cursor") }
 owner := mem.arena_alloc(16000000)
 defer { mem.arena_release(owner) }
 arena := owner
 raw_file: fail.Status
 raw := fs.read_all(arena, "DIRECTORY/raw", 6000000) catch { #panic("cannot read a fixture") }
 encoded_file: fail.Status
 encoded := fs.read_all(arena, "DIRECTORY/encoded", 2000000) catch { #panic("cannot read a fixture") }
 concatenated_file: fail.Status
 concatenated := fs.read_all(arena, "DIRECTORY/concatenated", 4000000) catch { #panic("cannot read a fixture") }
 unknown_file: fail.Status
 unknown := fs.read_all(arena, "DIRECTORY/unknown", 2000000) catch { #panic("cannot read a fixture") }
 if raw_file.failed || encoded_file.failed || concatenated_file.failed || unknown_file.failed { #panic("fixtures") }
 workspace := mem.push_bytes(arena, z.decoder_workspace_size(21))
 results(arena, encoded, unknown, workspace)
 verify(raw, unknown, workspace, 13, 21, false, 1)
 verify(raw, encoded, workspace, 1, 21, false, 1)
 verify(raw, encoded, workspace, 113, 21, false, 1)
 verify(raw, concatenated, workspace, 79, 21, false, 2)
 verify(raw, encoded[..encoded.len-1], workspace, 113, 21, true, 1)
 verify(raw, encoded, workspace[..1], 113, 21, true, 1)
}
'''

raw = bytes((i * 7 + i // 13) % 251 for i in range(40000))
out = c.create_string_buffer(lib.ZSTD_compressBound(len(raw)))
size = lib.ZSTD_compress(out, len(out), raw, len(raw), 3)
assert not lib.ZSTD_isError(size)
encoded = out.raw[:size]
ctx = lib.ZSTD_createCCtx()
assert ctx
try:
    assert not lib.ZSTD_isError(lib.ZSTD_CCtx_setParameter(ctx, 200, 0))
    size = lib.ZSTD_compress2(ctx, out, len(out), raw, len(raw))
    assert not lib.ZSTD_isError(size)
    unknown = out.raw[:size]
finally:
    lib.ZSTD_freeCCtx(ctx)
with tempfile.TemporaryDirectory(prefix='dyn-zstd-results-') as temporary:
    project = Path(temporary)
    for name, data in [('raw', raw), ('encoded', encoded), ('unknown', unknown), ('concatenated', encoded * 2)]:
        (project / name).write_bytes(data)
    panic_source = '''use mem "std/mem"
use "std/fail"
use z "std/compress/zstd"
fn main() {
 status: fail.Status
 storage: [1 + mem.ArenaBufferOverhead]u8
 arena := mem.arena_from_buffer(storage[..])
 arena = mem.arena_from_buffer(arena.data[..mem.ArenaHeader + 1])
 _ = z.compress(arena, &status, "exhaustion", 3)
}
'''
    for mode in ([], ['--release']):
        for program, panic in ((source.replace('DIRECTORY', str(project)), False), (panic_source, True)):
            (project / 'main.dyn').write_text(program)
            subprocess.run([str(DYN), 'build', str(project), '--quiet', '--no-cache', '--output', str(project / 'run'), *mode], cwd=ROOT, check=True, timeout=120)
            result = subprocess.run([str(project / 'run')], cwd=ROOT, capture_output=True, timeout=30)
            if panic:
                assert result.returncode != 0 and b'arena exhausted' in result.stderr.lower(), result
            else:
                assert result.returncode == 0, result.stderr.decode(errors='replace')
print('PASS zstd-results: native fixtures, portable kinds, unknown size, rollback, retained codes, sticky callbacks, concatenation, arena panic; debug/release')
