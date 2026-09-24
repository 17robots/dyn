#!/usr/bin/env python3
"""Native reference frames; arena-backed static context, small reusable I/O buffers."""
import ctypes
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn')).resolve())
lib=ctypes.CDLL('libzstd.so')
lib.ZSTD_compressBound.argtypes=[ctypes.c_size_t];lib.ZSTD_compressBound.restype=ctypes.c_size_t
lib.ZSTD_compress.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int];lib.ZSTD_compress.restype=ctypes.c_size_t
lib.ZSTD_isError.argtypes=[ctypes.c_size_t];lib.ZSTD_isError.restype=ctypes.c_uint
raw=random.Random(47).randbytes(400000)*12
out=ctypes.create_string_buffer(lib.ZSTD_compressBound(len(raw)))
size=lib.ZSTD_compress(out,len(out),raw,len(raw),3);assert not lib.ZSTD_isError(size)
encoded=out.raw[:size]
SOURCE='''use "std/compress/zstd" z
use "std/io" io
use "std/mem" mem
use "std/fs" fs
use "std/bytes" bytes
struct Input { source: []const u8, at: usize, chunk: usize }
fn read(data: rawptr, destination: []u8) io.Result {
 state := #cast(*Input) data
 amount := #len(state.source) - state.at
 if amount > state.chunk { amount = state.chunk }
 if amount > #len(destination) { amount = #len(destination) }
 _ = mem.copy(destination[..amount], state.source[state.at..state.at + amount]) state.at += amount
 status := io.Status.Complete if state.at == #len(state.source) { status = io.Status.End }
 return io.Result{ transferred: amount, status: status }
}
fn verify(raw: []const u8, encoded: []const u8, workspace: []u8, chunk: usize, window: u32, bad: bool, repeats: usize) {
 input := Input{ source: encoded, chunk: chunk }
 compressed: [113]u8 = [] output: [8191]u8 = []
 state := z.decoder(io.Reader{ data: #cast(rawptr) &input, read: &read }, compressed[..], workspace, window)
 reader := z.decoder_reader(&state) total: usize = 0
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
   total += 1 at += 1
  }
  if result.status == io.Status.End {
   if bad || total != #len(raw) * repeats { #panic("zstd completion") }
   if io.read(reader, output[..]).status != io.Status.End { #panic("zstd sticky end") }
   return
  }
  if result.transferred == 0 { #panic("zstd stall") }
 }
}
fn main() {
 owner := mem.arena_create(16000000) if !owner.ok { #panic("storage") }
 defer { _ = mem.arena_release(&owner.arena) }
 arena := &owner.arena
 raw := fs.read_all(arena, "DIRECTORY/raw", 6000000)
 encoded := fs.read_all(arena, "DIRECTORY/encoded", 2000000)
 concatenated := fs.read_all(arena, "DIRECTORY/concatenated", 4000000)
 if !raw.ok || !encoded.ok || !concatenated.ok { #panic("read fixtures") }
 workspace := mem.arena_push(arena, z.decoder_workspace_size(21), 8)[..z.decoder_workspace_size(21)]
 verify(raw.data, encoded.data, workspace, 1, 21, false, 1)
 verify(raw.data, encoded.data, workspace, 113, 21, false, 1)
 verify(raw.data, concatenated.data, workspace, 79, 21, false, 2)
 verify(raw.data, encoded.data[..#len(encoded.data)-1], workspace, 113, 21, true, 1)
 verify(raw.data, encoded.data, workspace, 113, 10, true, 1)
 verify(raw.data, encoded.data, workspace[..1], 113, 21, true, 1)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-zstd-stream-') as tmp:
    path=Path(tmp);(path/'raw').write_bytes(raw);(path/'encoded').write_bytes(encoded);(path/'concatenated').write_bytes(encoded*2)
    (path/'main.dyn').write_text(SOURCE.replace('DIRECTORY',str(path)))
    for mode in ([],['--release']):
        subprocess.run([DYN,'build',str(path),'--quiet','--no-cache','--output',str(path/'run'),*mode],cwd=ROOT,check=True)
        try:
            subprocess.run([str(path/'run')],cwd=ROOT,check=True,timeout=60)
        except subprocess.SubprocessError:
            failure = ROOT/'build/zstd-streaming-failure'
            shutil.copytree(path, failure, dirs_exist_ok=True)
            (failure/'main.dyn').write_text((failure/'main.dyn').read_text().replace(str(path), str(failure)))
            raise
print('PASS zstd streaming: 4.8 MB native reference, concatenation, truncation, window/workspace limits, debug/release')
