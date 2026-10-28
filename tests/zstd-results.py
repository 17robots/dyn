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
use "std/fs" fs
use "std/bytes" bytes
struct Input { source: []const u8, at: usize, chunk: usize }
fn read(data: rawptr, destination: []u8) io.Result {
 state := #cast(*Input, data)
 amount := #len(state.source) - state.at
 if amount > state.chunk { amount = state.chunk }
 if amount > #len(destination) { amount = #len(destination) }
 _ = mem.copy(destination[..amount], state.source[state.at..state.at + amount])
 state.at += amount
 status := io.Status.Complete
 if state.at == #len(state.source) { status = io.Status.End }
 return io.Result{ transferred: amount, status: status }
}
fn verify(raw: []const u8, encoded: []const u8, workspace: []u8, chunk: usize, window: u32, bad: bool, repeats: usize) {
 input := Input{ source: encoded, chunk: chunk }
 compressed: [113]u8 = []
 output: [8191]u8 = []
 state := z.decoder(io.Reader{ data: #cast(rawptr, &input), read: read }, compressed[..], workspace, window)
 reader := z.decoder_reader(&state)
 total: usize = 0
 for {
  result := io.read(reader, output[..])
  if result.status == io.Status.Error {
   if !bad { #panic("zstd unexpected error") }
   if io.read(reader, output[..]).error != result.error { #panic("zstd sticky error") }
   return
  }
  at: usize = 0
  for at < result.transferred {
   if total >= #len(raw) * repeats || output[at] != raw[total % #len(raw)] { #panic("zstd output") }
   total += 1
   at += 1
  }
  if result.status == io.Status.End {
   if bad || total != #len(raw) * repeats { #panic("zstd completion") }
   if io.read(reader, output[..]).status != io.Status.End { #panic("zstd sticky end") }
   return
  }
  if result.transferred == 0 { #panic("zstd stall") }
 }
}
'''
source = SOURCE
source = source.replace('mem.arena_push_or_panic', 'mem.arena_push_uninit')
source = source.replace('use "std/bytes" bytes', 'use "std/bytes" bytes\nuse "std/errors" errors')
extra = '''
struct Failure { calls: usize, code: isize }
fn fail(data: rawptr, destination: []u8) io.Result {
 state := #cast(*Failure, data)
 state.calls += 1
 return io.Result{ kind: errors.Kind.PermissionDenied, error: state.code, status: io.Status.Error }
}
fn results(arena: *mem.Arena, encoded: []const u8, unknown: []const u8, workspace: []u8) {
 packed := z.compress(arena, "portable zstd", 3)
 if !packed.ok || packed.kind != errors.Kind.None || packed.error != 0 { #panic("compress success") }
 unpacked := z.decompress(arena, packed.value)
 if !unpacked.ok || unpacked.kind != errors.Kind.None || #len(unpacked.value) != 13 { #panic("roundtrip") }
 mark := mem.arena_used(arena)
 bad := z.decompress(arena, "bad")
 if bad.ok || bad.kind != errors.Kind.InvalidInput || bad.error != 0 || #len(bad.value) != 0 || mem.arena_used(arena) != mark { #panic("malformed result") }
 size := z.frame_size(unknown)
 if !size.ok || size.known || size.kind != errors.Kind.None { #panic("unknown valid frame") }
 unsupported := z.decompress(arena, unknown)
 if unsupported.ok || unsupported.kind != errors.Kind.Unsupported || unsupported.error != 0 || mem.arena_used(arena) != mark { #panic("unknown arena unsupported") }
 // Header retains a valid known size, while truncation fails after allocation.
 broken := z.decompress(arena, encoded[..#len(encoded)-1])
 if broken.ok || broken.kind != errors.Kind.InvalidInput || broken.provider_code == 0 || broken.error != 0 || #len(broken.value) != 0 || mem.arena_used(arena) != mark { #panic("provider rollback") }
 code: isize = 0
 for code < 2 {
  upstream := Failure{ code: code }
  compressed: [17]u8 = []
  output: [11]u8 = []
  state := z.decoder(io.Reader{ data: &upstream, read: fail }, compressed[..], workspace, 21)
  reader := z.decoder_reader(&state)
  first := io.read(reader, output[..])
  callback := reader.read
  replay := callback(reader.data, output[..0])
  if first.status != io.Status.Error || first.kind != errors.Kind.PermissionDenied || first.error != code || replay.status != io.Status.Error || replay.kind != first.kind || replay.error != code || upstream.calls != 1 || state.provider_code != 0 { #panic("sticky upstream native zero / empty callback") }
  code += 1
 }
 compressed: [17]u8 = []
 output: [11]u8 = []
 input := Input{ source: "bad", chunk: 3 }
 state := z.decoder(io.Reader{ data: &input, read: read }, compressed[..], workspace, 21)
 reader := z.decoder_reader(&state)
 failed := io.read(reader, output[..])
 callback := reader.read
 replay := callback(reader.data, output[..0])
 if failed.status != io.Status.Error || failed.kind != errors.Kind.InvalidInput || failed.error != 0 || state.provider_code == 0 || replay.kind != failed.kind || replay.status != io.Status.Error { #panic("sticky provider diagnostic") }
}
'''
source = source + extra + r'''
fn main() {
 invalid := z.Decoder{offset:1}
 adapter := z.decoder_reader(&invalid)
 destination: [1]u8
 failed_invalid := io.read(adapter,destination[..])
 if failed_invalid.status!=io.Status.Error || failed_invalid.kind!=errors.Kind.InvalidState || failed_invalid.error!=0 || !invalid.failed { #panic("invalid decoder cursor") }
 invalid.offset=0
 replay_invalid:=adapter.read(adapter.data,destination[..0])
 if replay_invalid.status!=io.Status.Error || replay_invalid.kind!=errors.Kind.InvalidState || replay_invalid.error!=0 { #panic("sticky invalid decoder cursor") }
 owner := mem.arena_create(16000000)
 defer { mem.arena_release(owner) }
 arena := owner
 raw := fs.read_all(arena, "DIRECTORY/raw", 6000000)
 encoded := fs.read_all(arena, "DIRECTORY/encoded", 2000000)
 concatenated := fs.read_all(arena, "DIRECTORY/concatenated", 4000000)
 unknown := fs.read_all(arena, "DIRECTORY/unknown", 2000000)
 if !raw.ok || !encoded.ok || !concatenated.ok || !unknown.ok { #panic("fixtures") }
 workspace := mem.arena_push_uninit(arena, z.decoder_workspace_size(21), 8)[..z.decoder_workspace_size(21)]
 results(arena, encoded.value, unknown.value, workspace)
 verify(raw.value, unknown.value, workspace, 13, 21, false, 1)
 verify(raw.value, encoded.value, workspace, 1, 21, false, 1)
 verify(raw.value, encoded.value, workspace, 113, 21, false, 1)
 verify(raw.value, concatenated.value, workspace, 79, 21, false, 2)
 verify(raw.value, encoded.value[..#len(encoded.value)-1], workspace, 113, 21, true, 1)
 verify(raw.value, encoded.value, workspace[..1], 113, 21, true, 1)
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
use "std/compress/zstd" z
fn main() {
 storage: [1 + mem.ArenaBufferOverhead]u8 = []
 arena := mem.arena_from_buffer(storage[..])
 arena = mem.arena_from_buffer(arena.data[..mem.ArenaHeader + 1])
 _ = z.compress(arena, "exhaustion", 3)
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
