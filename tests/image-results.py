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
use "std/parse" parse
use "std/mem" mem
fn main() {
  storage: [8192]u8
  arena := mem.arena_from_buffer(storage[..])
  pixels: [8]u8 = [255,0,0,255,0,255,0,128]
  p := png.encode(arena, pixels[..], 2, 1, 4)
  if p.failure.kind != parse.Kind.Ok { #panic("PNG encode") }
  pi := png.inspect(p.value)
  if pi.failure.kind != parse.Kind.Ok || !pi.value.valid || pi.value.width != 2 { #panic("PNG inspect") }
  pd := png.decode(arena, p.value)
  if pd.failure.kind != parse.Kind.Ok || pd.value.info.width != 2 || #len(pd.value.pixels) != 8 { #panic("PNG decode") }
  for i in 0..8 { if pd.value.pixels[i] != pixels[i] { #panic("PNG pixels") } }
  q := qoi.encode(arena, pixels[..], 2, 1, 4, true)
  qi := qoi.inspect(q.value)
  qd := qoi.decode(arena, q.value)
  if q.failure.kind != parse.Kind.Ok || qi.failure.kind != parse.Kind.Ok || qd.failure.kind != parse.Kind.Ok || !qi.value.valid || qd.value.info.width != 2 { #panic("QOI roundtrip") }
  for i in 0..8 { if qd.value.pixels[i] != pixels[i] { #panic("QOI pixels") } }
  external: [70]u8 = [137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,0,0,0,1,0,0,0,1,8,6,0,0,0,31,21,196,137,0,0,0,13,73,68,65,84,120,156,99,248,207,192,240,31,0,5,0,1,255,137,153,61,29,0,0,0,0,73,69,78,68,174,66,96,130]
  independent := png.decode(arena, external[..])
  if independent.failure.kind != parse.Kind.Ok || independent.value.pixels[0] != 255 || independent.value.pixels[3] != 255 { #panic("external PNG") }
  for c in 1..5 {
    channels := #cast(u8, c)
    enc := png.encode(arena, pixels[..c], 1, 1, channels)
    dec := png.decode(arena, enc.value)
    if enc.failure.kind != parse.Kind.Ok || dec.failure.kind != parse.Kind.Ok || #len(dec.value.pixels) != c { #panic("PNG channels") }
    for i in 0..c { if dec.value.pixels[i] != pixels[i] { #panic("PNG channels pixels") } }
  }
  rgb := qoi.encode(arena, pixels[..3], 1, 1, 3, false)
  rgbd := qoi.decode(arena, rgb.value)
  if rgb.failure.kind != parse.Kind.Ok || rgbd.failure.kind != parse.Kind.Ok || rgbd.value.info.srgb || rgbd.value.pixels[3] != 255 { #panic("QOI RGB") }
  if p.failure.kind != parse.Kind.Ok || p.offset != 0 ||
    pi.failure.kind != parse.Kind.Ok || pi.offset != 0 ||
    pd.failure.kind != parse.Kind.Ok || pd.offset != 0 ||
    q.failure.kind != parse.Kind.Ok || q.offset != 0 ||
    qi.failure.kind != parse.Kind.Ok || qi.offset != 0 ||
    qd.failure.kind != parse.Kind.Ok || qd.offset != 0 {
    #panic("success metadata")
  }
  if pi.value.height != 1 || pi.value.channels != 4 || !pd.value.info.valid ||
    pd.value.info.height != 1 || pd.value.info.channels != 4 ||
    qi.value.width != 2 || qi.value.height != 1 || qi.value.channels != 4 || !qi.value.srgb ||
    !qd.value.info.valid || qd.value.info.height != 1 || qd.value.info.channels != 4 || !qd.value.info.srgb {
    #panic("success image info")
  }
  pzero: png.Result
  qzero: qoi.Result
  pizero: png.InfoResult
  qizero: qoi.InfoResult
  pezero: png.EncodeResult
  qezero: qoi.EncodeResult
  if pzero.value.info.valid || qzero.value.info.valid || pizero.value.valid || qizero.value.valid ||
    #len(pzero.value.pixels) != 0 || #len(qzero.value.pixels) != 0 ||
    #len(pezero.value) != 0 || #len(qezero.value) != 0 ||
    pzero.failure.kind != parse.Kind.Ok || qzero.failure.kind != parse.Kind.Ok ||
    pzero.offset != 0 || qzero.offset != 0 ||
    false { #panic("zero results") }
  mark := mem.arena_mark(arena)
  marker_original := q.value[#len(q.value)-1]
  q.value[#len(q.value)-1] = 99
  corrupt := qoi.decode(arena, q.value)
  if corrupt.failure.kind == parse.Kind.Ok || corrupt.failure.kind != parse.Kind.Syntax || #len(corrupt.value.pixels) != 0 || mem.arena_mark(arena) != mark { #panic("QOI end marker") }
  q.value[#len(q.value)-1] = marker_original
  excessive: [23]u8 = [113,111,105,102,0,0,0,1,0,0,0,1,4,0,253,0,0,0,0,0,0,0,1]
  runbad := qoi.decode(arena, excessive[..])
  if runbad.failure.kind == parse.Kind.Ok || runbad.failure.kind != parse.Kind.Syntax || #len(runbad.value.pixels) != 0 || mem.arena_mark(arena) != mark { #panic("QOI excessive run") }
  extra_payload: [24]u8 = [113,111,105,102,0,0,0,1,0,0,0,1,4,0,192,192,0,0,0,0,0,0,0,1]
  trailingbad := qoi.decode(arena, extra_payload[..])
  if trailingbad.failure.kind == parse.Kind.Ok || trailingbad.failure.kind != parse.Kind.Syntax || #len(trailingbad.value.pixels) != 0 || mem.arena_mark(arena) != mark { #panic("QOI trailing payload") }
  p.value[29] ^= 1
  bad := png.decode(arena, p.value)
  if bad.failure.kind == parse.Kind.Ok || bad.failure.kind != parse.Kind.Syntax || bad.offset != 29 || #len(bad.value.pixels) != 0 || bad.value.info.valid || mem.arena_mark(arena) != mark { #panic("PNG malformed rollback") }
  truncated: [22]u8 = ['q','o','i','f',0,0,0,1,0,0,0,1,4,0,0,0,0,0,0,0,0,1]
  qb := qoi.decode(arena, truncated[..])
  if qb.failure.kind == parse.Kind.Ok || qb.offset != 14 || qb.value.info.valid || #len(qb.value.pixels) != 0 || mem.arena_mark(arena) != mark { #panic("QOI malformed rollback") }
  empty: [0]u8
  pbad := png.inspect(empty[..])
  qbad := qoi.inspect(empty[..])
  if pbad.failure.kind == parse.Kind.Ok || qbad.failure.kind == parse.Kind.Ok || pbad.failure.kind != parse.Kind.Syntax || qbad.failure.kind != parse.Kind.Syntax ||
    pbad.offset != 0 || qbad.offset != 0 ||
    pbad.value.valid || qbad.value.valid ||
    pbad.value.width != 0 || qbad.value.width != 0 { #panic("inspect malformed") }
  pe := png.encode(arena, empty[..], 0, 1, 4)
  qe := qoi.encode(arena, empty[..], 1, 1, 4, true)
  if #len(pe.value) != 0 || #len(qe.value) != 0 || pe.offset != 0 || qe.offset != 0 || pe.failure.kind == parse.Kind.Ok || pe.failure.kind != parse.Kind.Syntax || qe.failure.kind == parse.Kind.Ok || qe.failure.kind != parse.Kind.Syntax || mem.arena_mark(arena) != mark { #panic("validation") }
  po := png.encode(arena, empty[..], 4294967295, 4294967295, 4)
  qo := qoi.encode(arena, empty[..], 4294967295, 4294967295, 4, true)
  if po.failure.kind != parse.Kind.Overflow || qo.failure.kind != parse.Kind.Overflow || mem.arena_mark(arena) != mark { #panic("overflow") }

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
use "std/mem" mem
fn main() {
  backing: [mem.ArenaBufferOverhead+1]u8
  skip := (16-(#cast(usize,&backing[0]) & 15)) & 15
  arena := mem.arena_from_buffer(backing[skip..skip+mem.ArenaHeader+1])
  pixels: [4]u8 = [255,0,0,255]
  external: [70]u8 = [137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,0,0,0,1,0,0,0,1,8,6,0,0,0,31,21,196,137,0,0,0,13,73,68,65,84,120,156,99,248,207,192,240,31,0,5,0,1,255,137,153,61,29,0,0,0,0,73,69,78,68,174,66,96,130]
  OPERATION
}
'''
for operation in ('_=png.decode(arena,external[..])', '_=png.encode(arena,pixels[..],1,1,4)', '_=qoi.encode(arena,pixels[..],1,1,4,true)', '_=qoi.decode(arena,"qoif\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01\\x04\\x00\\xc0\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x01")'):
    with tempfile.TemporaryDirectory(prefix='dyn-image-exhaustion-') as directory:
        work = Path(directory)
        (work/'main.dyn').write_text(PANIC_SOURCE.replace('OPERATION', operation))
        for mode in ('debug', 'release'):
            output = work/'panic'
            subprocess.run([str(DYN),'build',str(work),'--'+mode,'--quiet','--no-cache','--output',str(output)],cwd=ROOT,env=ENV,check=True,timeout=120)
            result = subprocess.run([str(output)],capture_output=True,timeout=10)
            assert result.returncode == 101 and b'arena exhausted or alignment invalid' in result.stderr.lower(), (operation,mode,result)
print('PASS image arena exhaustion panics (debug/release)',flush=True)
