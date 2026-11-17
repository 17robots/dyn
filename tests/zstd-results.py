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

SOURCE = '''use "std/compress/zstd" z
use "std/io" io
use "std/mem" mem
use "std/fail"
use "std/fs" fs
use "std/bytes" bytes
struct Input { source: []const u8, at: usize, chunk: usize }
fn read(data: rawptr, status: *fail.Status, destination: []u8) usize {
 state := #cast(*Input, data)
 amount := #len(state.source) - state.at
 if amount > state.chunk { amount = state.chunk }
 if amount > #len(destination) { amount = #len(destination) }
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
  count := io.read(&status, reader, output[..])
  if status.failed {
   if !bad { #panic("zstd unexpected error") }
   again: fail.Status
   _ = io.read(&again, reader, output[..])
   if again.failure.native != status.failure.native || again.failure.kind != status.failure.kind { #panic("zstd sticky error") }
   return
  }
  at: usize = 0
  for at < count {
   if total >= #len(raw) * repeats || output[at] != raw[total % #len(raw)] { #panic("zstd output") }
   total += 1
   at += 1
  }
  if count == 0 {
   if bad || total != #len(raw) * repeats { #panic("zstd completion") }
   end: fail.Status
   if io.read(&end, reader, output[..]) != 0 || end.failed { #panic("zstd sticky end") }
   return
  }
 }
}
'''
source = SOURCE
extra = '''
struct Upstream { calls: usize, code: isize }
fn refuse(data: rawptr, status: *fail.Status, destination: []u8) usize {
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
 if #len(unpacked) != 13 { #panic("roundtrip") }
 mark := mem.arena_used(arena)
 bad: fail.Status
 bad_value := z.decompress(arena, &bad, "bad")
 if bad.failure.kind != fail.Kind.InvalidInput || #len(bad_value) != 0 || mem.arena_used(arena) != mark { #panic("malformed result") }
 size := z.frame_size(&status, unknown)
 if size.known { #panic("unknown valid frame") }
 unsupported: fail.Status
 _ = z.decompress(arena, &unsupported, unknown)
 if unsupported.failure.kind != fail.Kind.Unsupported || mem.arena_used(arena) != mark { #panic("unknown arena unsupported") }
 // Header retains a valid known size, while truncation fails after allocation.
 broken: fail.Status
 broken_value := z.decompress(arena, &broken, encoded[..#len(encoded)-1])
 if broken.failure.kind != fail.Kind.InvalidInput || broken.failure.native == 0 || #len(broken_value) != 0 || mem.arena_used(arena) != mark { #panic("provider rollback") }
 code: isize = 0
 for code < 2 {
  upstream := Upstream{ code: code }
  compressed: [17]u8
  output: [11]u8
  state := z.decoder(io.Reader{ data: &upstream, read: refuse }, compressed[..], workspace, 21)
  reader := z.decoder_reader(&state)
  first: fail.Status
  _ = io.read(&first, reader, output[..])
  replay: fail.Status
  _ = reader.read(reader.data, &replay, output[..0])
  if !first.failed || first.failure.kind != fail.Kind.PermissionDenied || first.failure.native != code || !replay.failed || replay.failure.kind != first.failure.kind || replay.failure.native != code || upstream.calls != 1 { #panic("sticky upstream native zero / empty callback") }
  code += 1
 }
 compressed: [17]u8
 output: [11]u8
 input := Input{ source: "bad", chunk: 3 }
 state := z.decoder(io.Reader{ data: &input, read: read }, compressed[..], workspace, 21)
 reader := z.decoder_reader(&state)
 failed: fail.Status
 _ = io.read(&failed, reader, output[..])
 replay: fail.Status
 _ = reader.read(reader.data, &replay, output[..0])
 if !failed.failed || failed.failure.kind != fail.Kind.InvalidInput || failed.failure.native == 0 || replay.failure.kind != failed.failure.kind || !replay.failed { #panic("sticky provider diagnostic") }
}
'''
source = source + extra + r'''
fn main() {
 invalid := z.Decoder{offset:1}
 adapter := z.decoder_reader(&invalid)
 destination: [1]u8
 failed_invalid: fail.Status
 _ = io.read(&failed_invalid, adapter, destination[..])
 if !failed_invalid.failed || failed_invalid.failure.kind != fail.Kind.InvalidState || failed_invalid.failure.native != 0 || !invalid.failed { #panic("invalid decoder cursor") }
 invalid.offset=0
 replay_invalid: fail.Status
 _ = adapter.read(adapter.data, &replay_invalid, destination[..0])
 if !replay_invalid.failed || replay_invalid.failure.kind != fail.Kind.InvalidState || replay_invalid.failure.native != 0 { #panic("sticky invalid decoder cursor") }
 owner := mem.arena_alloc(16000000)
 defer { mem.arena_release(owner) }
 arena := owner
 raw_file: fail.Status
 raw := fs.read_all(arena, &raw_file, "DIRECTORY/raw", 6000000)
 encoded_file: fail.Status
 encoded := fs.read_all(arena, &encoded_file, "DIRECTORY/encoded", 2000000)
 concatenated_file: fail.Status
 concatenated := fs.read_all(arena, &concatenated_file, "DIRECTORY/concatenated", 4000000)
 unknown_file: fail.Status
 unknown := fs.read_all(arena, &unknown_file, "DIRECTORY/unknown", 2000000)
 if raw_file.failed || encoded_file.failed || concatenated_file.failed || unknown_file.failed { #panic("fixtures") }
 workspace := #slice(mem.arena_push_uninit(arena, z.decoder_workspace_size(21), 8), z.decoder_workspace_size(21))
 results(arena, encoded, unknown, workspace)
 verify(raw, unknown, workspace, 13, 21, false, 1)
 verify(raw, encoded, workspace, 1, 21, false, 1)
 verify(raw, encoded, workspace, 113, 21, false, 1)
 verify(raw, concatenated, workspace, 79, 21, false, 2)
 verify(raw, encoded[..#len(encoded)-1], workspace, 113, 21, true, 1)
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
    panic_source = '''use "std/mem" mem
use "std/fail"
use "std/compress/zstd" z
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
