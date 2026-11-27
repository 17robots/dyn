#!/usr/bin/env python3
"""Portable PNG/QOI arena ownership, result metadata, and failure rollback."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get("DYN", ROOT / "build/dyn-release")).resolve()
ENV = dict(os.environ, DYN_SDK=str(ROOT))
SOURCE = r'''
use png "std/image/png"
use qoi "std/image/qoi"
use mem "std/mem"
use io "std/io"
use parse "std/parse"
enum Kind { Ok, InvalidInput, Capacity, Unsupported }
struct Failure { kind: Kind, offset: usize }
fn failure_of(err: parse.ParseErr) Failure {
 case err {
  .Invalid(at) => { return Failure{ kind: Kind.InvalidInput, offset: at } }
  .TooLarge(at) => { return Failure{ kind: Kind.Capacity, offset: at } }
  .Unsupported(at) => { return Failure{ kind: Kind.Unsupported, offset: at } }
 }
}
fn png_failure(arena: *mem.Arena, data: []const u8) Failure {
  _ = png.decode(arena, data) catch err { return failure_of(err) }
  #panic("PNG should fail")
}
fn qoi_failure(arena: *mem.Arena, data: []const u8) Failure {
  _ = qoi.decode(arena, data) catch err { return failure_of(err) }
  #panic("QOI should fail")
}
fn png_inspect_failure(data: []const u8) Failure {
  _ = png.inspect(data) catch err { return failure_of(err) }
  #panic("PNG inspect should fail")
}
fn qoi_inspect_failure(data: []const u8) Failure {
  _ = qoi.inspect(data) catch err { return failure_of(err) }
  #panic("QOI inspect should fail")
}
// An encode's failure: Ok, InvalidInput or Capacity.
fn io_kind(err: io.IoErr) Kind {
  case err {
    .InvalidInput => { return Kind.InvalidInput }
    .Capacity => { return Kind.Capacity }
    _ => { return Kind.Unsupported }
  }
}
fn png_encode_kind(arena: *mem.Arena, pixels: []const u8, width, height: usize, channels: u8) Kind {
  _ = png.encode(arena, pixels, width, height, channels) catch err { return io_kind(err) }
  return Kind.Ok
}
fn qoi_encode_kind(arena: *mem.Arena, pixels: []const u8, width, height: usize, channels: u8, srgb: bool) Kind {
  _ = qoi.encode(arena, pixels, width, height, channels, srgb) catch err { return io_kind(err) }
  return Kind.Ok
}
fn main() {
  storage: [8192]u8
  arena := mem.arena_from_buffer(storage[..])
  pixels: [8]u8 = [255,0,0,255,0,255,0,128]
  p := png.encode(arena, pixels[..], 2, 1, 4) catch { #panic("unexpected failure") }
  pi := png.inspect(p) catch { #panic("unexpected failure") }
  if pi.width != 2 { #panic("PNG inspect") }
  pd := png.decode(arena, p) catch { #panic("unexpected failure") }
  if pd.info.width != 2 || pd.pixels.len != 8 { #panic("PNG decode") }
  for i in 0..8 { if pd.pixels[i] != pixels[i] { #panic("PNG pixels") } }
  q := qoi.encode(arena, pixels[..], 2, 1, 4, true) catch { #panic("unexpected failure") }
  qi := qoi.inspect(q) catch { #panic("unexpected failure") }
  qd := qoi.decode(arena, q) catch { #panic("unexpected failure") }
  if qi.width != 2 || qd.info.width != 2 { #panic("QOI roundtrip") }
  for i in 0..8 { if qd.pixels[i] != pixels[i] { #panic("QOI pixels") } }
  external: [70]u8 = [137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,0,0,0,1,0,0,0,1,8,6,0,0,0,31,21,196,137,0,0,0,13,73,68,65,84,120,156,99,248,207,192,240,31,0,5,0,1,255,137,153,61,29,0,0,0,0,73,69,78,68,174,66,96,130]
  independent := png.decode(arena, external[..]) catch { #panic("unexpected failure") }
  if independent.pixels[0] != 255 || independent.pixels[3] != 255 { #panic("external PNG") }
  for c in 1..5 {
    channels := #cast(u8, c)
    enc := png.encode(arena, pixels[..c], 1, 1, channels) catch { #panic("unexpected failure") }
    dec := png.decode(arena, enc) catch { #panic("unexpected failure") }
    if dec.pixels.len != c { #panic("PNG channels") }
    for i in 0..c { if dec.pixels[i] != pixels[i] { #panic("PNG channels pixels") } }
  }
  rgb := qoi.encode(arena, pixels[..3], 1, 1, 3, false) catch { #panic("unexpected failure") }
  rgbd := qoi.decode(arena, rgb) catch { #panic("unexpected failure") }
  if rgbd.info.srgb || rgbd.pixels[3] != 255 { #panic("QOI RGB") }
  if pi.height != 1 || pi.channels != 4 || pd.info.width == 0 ||
    pd.info.height != 1 || pd.info.channels != 4 ||
    qi.width != 2 || qi.height != 1 || qi.channels != 4 || !qi.srgb ||
    qd.info.width == 0 || qd.info.height != 1 || qd.info.channels != 4 || !qd.info.srgb {
    #panic("success image info")
  }
  pzero: png.Image
  qzero: qoi.Image
  if pzero.info.width != 0 || qzero.info.width != 0 || pzero.pixels.len != 0 || qzero.pixels.len != 0 { #panic("zero values") }
  mark := mem.arena_mark(arena)
  marker_original := q[q.len-1]
  q[q.len-1] = 99
  corrupt := qoi_failure(arena, q)
  if corrupt.kind != Kind.InvalidInput || mem.arena_mark(arena) != mark { #panic("QOI end marker") }
  q[q.len-1] = marker_original
  excessive: [23]u8 = [113,111,105,102,0,0,0,1,0,0,0,1,4,0,253,0,0,0,0,0,0,0,1]
  runbad := qoi_failure(arena, excessive[..])
  if runbad.kind != Kind.InvalidInput || mem.arena_mark(arena) != mark { #panic("QOI excessive run") }
  extra_payload: [24]u8 = [113,111,105,102,0,0,0,1,0,0,0,1,4,0,192,192,0,0,0,0,0,0,0,1]
  trailingbad := qoi_failure(arena, extra_payload[..])
  if trailingbad.kind != Kind.InvalidInput || mem.arena_mark(arena) != mark { #panic("QOI trailing payload") }
  p[29] ^= 1
  bad := png_failure(arena, p)
  if bad.kind != Kind.InvalidInput || bad.offset != 29 || mem.arena_mark(arena) != mark { #panic("PNG malformed rollback") }
  truncated: [22]u8 = ['q','o','i','f',0,0,0,1,0,0,0,1,4,0,0,0,0,0,0,0,0,1]
  qb := qoi_failure(arena, truncated[..])
  if qb.offset != 14 || mem.arena_mark(arena) != mark { #panic("QOI malformed rollback") }
  empty: [0]u8
  pbad := png_inspect_failure(empty[..])
  qbad := qoi_inspect_failure(empty[..])
  if pbad.kind != Kind.InvalidInput || qbad.kind != Kind.InvalidInput ||
    pbad.offset != 0 || qbad.offset != 0 { #panic("inspect malformed") }
  if png_encode_kind(arena, empty[..], 0, 1, 4) != Kind.InvalidInput || qoi_encode_kind(arena, empty[..], 1, 1, 4, true) != Kind.InvalidInput || mem.arena_mark(arena) != mark { #panic("validation") }
  if png_encode_kind(arena, empty[..], 4294967295, 4294967295, 4) != Kind.Capacity || qoi_encode_kind(arena, empty[..], 4294967295, 4294967295, 4, true) != Kind.Capacity || mem.arena_mark(arena) != mark { #panic("overflow") }

}
'''

with tempfile.TemporaryDirectory(prefix="dyn-image-results-") as directory:
    work = Path(directory)
    (work / "main.dyn").write_text(SOURCE)
    for mode in ("debug", "release"):
        output = work / ("image-results-" + mode)
        subprocess.run([str(DYN), "build", str(work), "--" + mode,
                        "--quiet", "--no-cache", "--output", str(output)],
                       cwd=ROOT, env=ENV, check=True, timeout=120)
        result = subprocess.run([str(output)], capture_output=True, timeout=10)
        assert result.returncode == 0, (mode, result.returncode, result.stdout, result.stderr)
        print("PASS image result contracts " + mode, flush=True)

# Fixed arena exhaustion is a programming error, not an external-input result.
PANIC_SOURCE = '''use png "std/image/png"
use qoi "std/image/qoi"
use mem "std/mem"
fn main() {
  backing: [mem.ArenaBufferOverhead+1]u8
  skip := (16-(#cast(usize,&backing[0]) & 15)) & 15
  arena := mem.arena_from_buffer(backing[skip..skip+mem.ArenaHeader+1])
  pixels: [4]u8 = [255,0,0,255]
  external: [70]u8 = [137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,0,0,0,1,0,0,0,1,8,6,0,0,0,31,21,196,137,0,0,0,13,73,68,65,84,120,156,99,248,207,192,240,31,0,5,0,1,255,137,153,61,29,0,0,0,0,73,69,78,68,174,66,96,130]
  OPERATION
}
'''
for operation in ('_=png.decode(arena,external[..]) catch { #panic("failed") }', '_=png.encode(arena,pixels[..],1,1,4) catch { #panic("failed") }', '_=qoi.encode(arena,pixels[..],1,1,4,true) catch { #panic("failed") }', '_=qoi.decode(arena,"qoif\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01\\x04\\x00\\xc0\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x01") catch { #panic("failed") }'):
    with tempfile.TemporaryDirectory(prefix='dyn-image-exhaustion-') as directory:
        work = Path(directory)
        (work/'main.dyn').write_text(PANIC_SOURCE.replace('OPERATION', operation))
        for mode in ('debug', 'release'):
            output = work/'panic'
            subprocess.run([str(DYN),'build',str(work),'--'+mode,'--quiet','--no-cache','--output',str(output)],cwd=ROOT,env=ENV,check=True,timeout=120)
            result = subprocess.run([str(output)],capture_output=True,timeout=10)
            assert result.returncode == 101 and b'arena exhausted' in result.stderr.lower(), (operation,mode,result)
print('PASS image arena exhaustion panics (debug/release)',flush=True)
