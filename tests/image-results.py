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
use "std/image/png" png
use "std/image/qoi" qoi
use "std/fail"
use "std/mem" mem
fn png_failure(arena: *mem.Arena, data: []const u8) fail.Failure {
  status: fail.Status
  image := png.decode(arena, &status, data)
  if !status.failed || #len(image.pixels) != 0 || image.info.width != 0 { #panic("PNG should fail") }
  return status.failure
}
fn qoi_failure(arena: *mem.Arena, data: []const u8) fail.Failure {
  status: fail.Status
  image := qoi.decode(arena, &status, data)
  if !status.failed || #len(image.pixels) != 0 || image.info.width != 0 { #panic("QOI should fail") }
  return status.failure
}
fn main() {
  storage: [8192]u8
  arena := mem.arena_from_buffer(storage[..])
  status := fail.Status{ on_failure: fail.panic_on_failure }
  pixels: [8]u8 = [255,0,0,255,0,255,0,128]
  p := png.encode(arena, &status, pixels[..], 2, 1, 4)
  pi := png.inspect(&status, p)
  if pi.width != 2 { #panic("PNG inspect") }
  pd := png.decode(arena, &status, p)
  if pd.info.width != 2 || #len(pd.pixels) != 8 { #panic("PNG decode") }
  for i in 0..8 { if pd.pixels[i] != pixels[i] { #panic("PNG pixels") } }
  q := qoi.encode(arena, &status, pixels[..], 2, 1, 4, true)
  qi := qoi.inspect(&status, q)
  qd := qoi.decode(arena, &status, q)
  if qi.width != 2 || qd.info.width != 2 { #panic("QOI roundtrip") }
  for i in 0..8 { if qd.pixels[i] != pixels[i] { #panic("QOI pixels") } }
  external: [70]u8 = [137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,0,0,0,1,0,0,0,1,8,6,0,0,0,31,21,196,137,0,0,0,13,73,68,65,84,120,156,99,248,207,192,240,31,0,5,0,1,255,137,153,61,29,0,0,0,0,73,69,78,68,174,66,96,130]
  independent := png.decode(arena, &status, external[..])
  if independent.pixels[0] != 255 || independent.pixels[3] != 255 { #panic("external PNG") }
  for c in 1..5 {
    channels := #cast(u8, c)
    enc := png.encode(arena, &status, pixels[..c], 1, 1, channels)
    dec := png.decode(arena, &status, enc)
    if #len(dec.pixels) != c { #panic("PNG channels") }
    for i in 0..c { if dec.pixels[i] != pixels[i] { #panic("PNG channels pixels") } }
  }
  rgb := qoi.encode(arena, &status, pixels[..3], 1, 1, 3, false)
  rgbd := qoi.decode(arena, &status, rgb)
  if rgbd.info.srgb || rgbd.pixels[3] != 255 { #panic("QOI RGB") }
  if pi.height != 1 || pi.channels != 4 || pd.info.width == 0 ||
    pd.info.height != 1 || pd.info.channels != 4 ||
    qi.width != 2 || qi.height != 1 || qi.channels != 4 || !qi.srgb ||
    qd.info.width == 0 || qd.info.height != 1 || qd.info.channels != 4 || !qd.info.srgb {
    #panic("success image info")
  }
  pzero: png.Image
  qzero: qoi.Image
  if pzero.info.width != 0 || qzero.info.width != 0 || #len(pzero.pixels) != 0 || #len(qzero.pixels) != 0 { #panic("zero values") }
  mark := mem.arena_mark(arena)
  marker_original := q[#len(q)-1]
  q[#len(q)-1] = 99
  corrupt := qoi_failure(arena, q)
  if corrupt.kind != fail.Kind.InvalidInput || mem.arena_mark(arena) != mark { #panic("QOI end marker") }
  q[#len(q)-1] = marker_original
  excessive: [23]u8 = [113,111,105,102,0,0,0,1,0,0,0,1,4,0,253,0,0,0,0,0,0,0,1]
  runbad := qoi_failure(arena, excessive[..])
  if runbad.kind != fail.Kind.InvalidInput || mem.arena_mark(arena) != mark { #panic("QOI excessive run") }
  extra_payload: [24]u8 = [113,111,105,102,0,0,0,1,0,0,0,1,4,0,192,192,0,0,0,0,0,0,0,1]
  trailingbad := qoi_failure(arena, extra_payload[..])
  if trailingbad.kind != fail.Kind.InvalidInput || mem.arena_mark(arena) != mark { #panic("QOI trailing payload") }
  p[29] ^= 1
  bad := png_failure(arena, p)
  if bad.kind != fail.Kind.InvalidInput || bad.offset != 29 || mem.arena_mark(arena) != mark { #panic("PNG malformed rollback") }
  truncated: [22]u8 = ['q','o','i','f',0,0,0,1,0,0,0,1,4,0,0,0,0,0,0,0,0,1]
  qb := qoi_failure(arena, truncated[..])
  if qb.offset != 14 || mem.arena_mark(arena) != mark { #panic("QOI malformed rollback") }
  empty: [0]u8
  pbad: fail.Status
  qbad: fail.Status
  pinfo := png.inspect(&pbad, empty[..])
  qinfo := qoi.inspect(&qbad, empty[..])
  if pbad.failure.kind != fail.Kind.InvalidInput || qbad.failure.kind != fail.Kind.InvalidInput ||
    pbad.failure.offset != 0 || qbad.failure.offset != 0 ||
    pinfo.width != 0 || qinfo.width != 0 { #panic("inspect malformed") }
  pe_status: fail.Status
  qe_status: fail.Status
  pe := png.encode(arena, &pe_status, empty[..], 0, 1, 4)
  qe := qoi.encode(arena, &qe_status, empty[..], 1, 1, 4, true)
  if #len(pe) != 0 || #len(qe) != 0 || pe_status.failure.kind != fail.Kind.InvalidInput || qe_status.failure.kind != fail.Kind.InvalidInput || mem.arena_mark(arena) != mark { #panic("validation") }
  po: fail.Status
  qo: fail.Status
  _ = png.encode(arena, &po, empty[..], 4294967295, 4294967295, 4)
  _ = qoi.encode(arena, &qo, empty[..], 4294967295, 4294967295, 4, true)
  if po.failure.kind != fail.Kind.Overflow || qo.failure.kind != fail.Kind.Overflow || mem.arena_mark(arena) != mark { #panic("overflow") }

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
PANIC_SOURCE = '''use "std/image/png" png
use "std/image/qoi" qoi
use "std/fail"
use "std/mem" mem
fn main() {
  status: fail.Status
  backing: [mem.ArenaBufferOverhead+1]u8
  skip := (16-(#cast(usize,&backing[0]) & 15)) & 15
  arena := mem.arena_from_buffer(backing[skip..skip+mem.ArenaHeader+1])
  pixels: [4]u8 = [255,0,0,255]
  external: [70]u8 = [137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,0,0,0,1,0,0,0,1,8,6,0,0,0,31,21,196,137,0,0,0,13,73,68,65,84,120,156,99,248,207,192,240,31,0,5,0,1,255,137,153,61,29,0,0,0,0,73,69,78,68,174,66,96,130]
  OPERATION
}
'''
for operation in ('_=png.decode(arena,&status,external[..])', '_=png.encode(arena,&status,pixels[..],1,1,4)', '_=qoi.encode(arena,&status,pixels[..],1,1,4,true)', '_=qoi.decode(arena,&status,"qoif\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01\\x04\\x00\\xc0\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x01")'):
    with tempfile.TemporaryDirectory(prefix='dyn-image-exhaustion-') as directory:
        work = Path(directory)
        (work/'main.dyn').write_text(PANIC_SOURCE.replace('OPERATION', operation))
        for mode in ('debug', 'release'):
            output = work/'panic'
            subprocess.run([str(DYN),'build',str(work),'--'+mode,'--quiet','--no-cache','--output',str(output)],cwd=ROOT,env=ENV,check=True,timeout=120)
            result = subprocess.run([str(output)],capture_output=True,timeout=10)
            assert result.returncode == 101 and b'arena exhausted or alignment invalid' in result.stderr.lower(), (operation,mode,result)
print('PASS image arena exhaustion panics (debug/release)',flush=True)
