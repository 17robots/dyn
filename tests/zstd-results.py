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
use fs "std/fs"
use bytes "std/bytes"
struct Input { source: []const u8, at: usize, chunk: usize }
fn read(data: rawptr, destination: []u8) usize!io.IoErr {
 state := #cast(*Input, data)
 amount := state.source.len - state.at
 if amount > state.chunk { amount = state.chunk }
 if amount > destination.len { amount = destination.len }
 _ = mem.copy(destination[..amount], state.source[state.at..state.at + amount])
 state.at += amount
 return amount
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
// One read's count, or the kind of its failure.
struct Read { count: usize, failure: Kind }
fn read_once(reader: io.Reader, destination: []u8) Read {
 count := io.read(reader, destination) catch err { return Read{ failure: kind_of(err) } }
 return Read{ count: count }
}
fn verify(raw: []const u8, encoded: []const u8, workspace: []u8, chunk: usize, window: u32, bad: bool, repeats: usize) {
 input := Input{ source: encoded, chunk: chunk }
 compressed: [113]u8
 output: [8191]u8
 state := z.decoder(io.Reader{ data: #cast(rawptr, &input), read: read }, compressed[..], workspace, window)
 reader := z.decoder_reader(&state)
 total: usize = 0
 for {
  got := read_once(reader, output[..])
  if got.failure != Kind.Ok {
   if !bad { #panic("zstd unexpected error") }
   again := read_once(reader, output[..])
   if again.failure != got.failure { #panic("zstd sticky error") }
   return
  }
  count := got.count
  at: usize = 0
  for at < count {
   if total >= raw.len * repeats || output[at] != raw[total % raw.len] { #panic("zstd output") }
   total += 1
   at += 1
  }
  if count == 0 {
   if bad || total != raw.len * repeats { #panic("zstd completion") }
   end := read_once(reader, output[..])
   if end.count != 0 || end.failure != Kind.Ok { #panic("zstd sticky end") }
   return
  }
 }
}
'''
source = SOURCE
extra = '''
struct Upstream { calls: usize }
fn refuse(data: rawptr, destination: []u8) usize!io.IoErr {
 state := #cast(*Upstream, data)
 state.calls += 1
 fail .PermissionDenied
}
fn decompress_err(arena: *mem.Arena, source: []const u8) Kind {
 _ = z.decompress(arena, source) catch err { return kind_of(err) }
 return Kind.Ok
}
fn results(arena: *mem.Arena, encoded: []const u8, unknown: []const u8, workspace: []u8) {
 squeezed := z.compress(arena, "portable zstd", 3) catch { #panic("compress") }
 unpacked := z.decompress(arena, squeezed) catch { #panic("decompress") }
 if unpacked.len != 13 { #panic("roundtrip") }
 mark := mem.arena_used(arena)
 if decompress_err(arena, "bad") != Kind.InvalidInput || mem.arena_used(arena) != mark { #panic("malformed result") }
 size := z.frame_size(unknown) catch { #panic("frame_size") }
 if size.known { #panic("unknown valid frame") }
 if decompress_err(arena, unknown) != Kind.Unsupported || mem.arena_used(arena) != mark { #panic("unknown arena unsupported") }
 // Header retains a valid known size, while truncation fails after allocation.
 if decompress_err(arena, encoded[..encoded.len-1]) != Kind.InvalidInput || mem.arena_used(arena) != mark { #panic("provider rollback") }
 upstream := Upstream{}
 compressed: [17]u8
 output: [11]u8
 state := z.decoder(io.Reader{ data: &upstream, read: refuse }, compressed[..], workspace, 21)
 reader := z.decoder_reader(&state)
 first := read_once(reader, output[..])
 replay := direct(reader, output[..0])
 if first.failure != Kind.PermissionDenied || replay != first.failure || upstream.calls != 1 { #panic("sticky upstream / empty callback") }
 bad_compressed: [17]u8
 bad_output: [11]u8
 input := Input{ source: "bad", chunk: 3 }
 bad_state := z.decoder(io.Reader{ data: &input, read: read }, bad_compressed[..], workspace, 21)
 bad_reader := z.decoder_reader(&bad_state)
 failed := read_once(bad_reader, bad_output[..])
 bad_replay := direct(bad_reader, bad_output[..0])
 if failed.failure != Kind.InvalidInput || bad_replay != failed.failure { #panic("sticky provider diagnostic") }
}
'''
source = source + extra + r'''
// Calls the adapter itself, even for an empty destination, which io.read
// would not pass on.
fn direct(reader: io.Reader, destination: []u8) Kind {
 _ = reader.read(reader.data, destination) catch err { return kind_of(err) }
 return Kind.Ok
}
fn main() {
 owner := mem.arena_alloc(16000000)
 defer { mem.arena_release(owner) }
 arena := owner
 raw := fs.read_all(arena, "DIRECTORY/raw", 6000000) catch { #panic("cannot read a fixture") }
 encoded := fs.read_all(arena, "DIRECTORY/encoded", 2000000) catch { #panic("cannot read a fixture") }
 concatenated := fs.read_all(arena, "DIRECTORY/concatenated", 4000000) catch { #panic("cannot read a fixture") }
 unknown := fs.read_all(arena, "DIRECTORY/unknown", 2000000) catch { #panic("cannot read a fixture") }
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
use z "std/compress/zstd"
fn main() {
 storage: [1 + mem.ArenaBufferOverhead]u8
 arena := mem.arena_from_buffer(storage[..])
 arena = mem.arena_from_buffer(arena.data[..mem.ArenaHeader + 1])
 _ = z.compress(arena, "exhaustion", 3) catch { #panic("compress failed") }
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
