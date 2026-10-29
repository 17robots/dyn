#!/usr/bin/env python3
"""Composite outlines compared with independently flattened TrueType glyphs."""
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
u16=lambda x:struct.pack('>H',x)
i16=lambda x:struct.pack('>h',x)
u32=lambda x:struct.pack('>I',x)
def bounds(points):
    return (math.floor(min(p[0] for p in points)),math.floor(min(p[1] for p in points)),math.ceil(max(p[0] for p in points)),math.ceil(max(p[1] for p in points))) if points else (0,0,0,0)
def header(contours,box): return i16(contours)+b''.join(i16(x) for x in box)
def simple(points,ends):
    data=header(len(ends),bounds(points))+b''.join(u16(x) for x in ends)+u16(0)+bytes(1 if p[2] else 0 for p in points)
    for axis in (0,1):
        previous=0
        for point in points:
            data+=i16(int(point[axis])-previous);previous=int(point[axis])
    return data+b'\0'*(len(data)%2)
def component(index,a=0,b=0,flags=3,matrix=()):
    arguments=(i16(a)+i16(b) if flags&2 else u16(a)+u16(b)) if flags&1 else struct.pack('bb' if flags&2 else 'BB',a,b)
    return u16(flags)+u16(index)+arguments+b''.join(i16(round(v*16384)) for v in matrix)
def transformed(points,xx=1,yx=0,xy=0,yy=1,dx=0,dy=0):
    return [(x*xx+y*xy+dx,x*yx+y*yy+dy,on) for x,y,on in points]
square=[(0,0,True),(1000,0,True),(1000,1000,True),(0,1000,True)]
curve=[(0,0,True),(500,1000,False),(1000,0,True)]
glyphs=[b'',simple(square,[3]),simple(curve,[2])]
metrics=[(1000,0)]*3
pairs=[]; failures=[]
def add(data,advance=2222,bearing=0):
    glyphs.append(data+b'\0'*(len(data)%2));metrics.append((advance,bearing));return len(glyphs)-1
def paired(records,points,ends,advance=2222,ref_advance=None,reference_points=None,reference_bearing=0,tail=b''):
    index=add(header(-1,bounds(points))+b''.join(records)+tail,advance)
    reference=add(simple(reference_points or points,ends),advance if ref_advance is None else ref_advance,reference_bearing)
    pairs.append((index,reference));return index
# The first component is a separate square; the second does not hide inside it.
base=component(1,flags=35)
for flag,values,xx,yx,xy,yy,dx,dy in (
    (8,(.5,),.5,0,0,.5,1500,250),
    (64,(.5,.25),.5,0,0,.25,1500,250),
    (128,(.5,.25,-.25,.5),.5,.25,-.25,.5,1750,250),
    (64,(-.5,.5),-.5,0,0,.5,2000,250),
):
    child=transformed(square,xx,yx,xy,yy,dx,dy)
    paired([base,component(1,dx,dy,3|flag,values)],square+child,[3,7])
# Scaled offsets and the recommended unscaled default, including conflicting flags.
for offset_flags,dx,dy in ((0x800,3000,500),(0x1000,1500,250),(0,1500,250),(0x1800,1500,250)):
    paired([base,component(1,dx,dy,3|8|offset_flags,(.5,))],square+transformed(square,.5,0,0,.5,1500,250),[3,7])
# Unsigned byte and word point-number attachment, both directions.
paired([base,component(1,1,0,0)],square+transformed(square,dx=1000),[3,7])
paired([base,component(1,3,2,1)],square+transformed(square,dx=-1000),[3,7])
# Byte XY arguments include negative values. No grid fitting in this renderer.
paired([base,component(2,-100,125,2|4)],square+transformed(curve,dx=-100,dy=125),[3,6])
# A matrix applied to a curve and nested composites retain quadratic controls.
curved=paired([component(2,0,0,3|64,(.5,.5))],transformed(curve,.5,0,0,.5),[2])
paired([base,component(curved,1500,250,3)],square+transformed(curve,.5,0,0,.5,1500,250),[3,6])
# Metric selection is independent of the parent's own advance.
paired([component(1,0,0,3|8|512,(.5,))],transformed(square,.5,0,0,.5),[3],ref_advance=500)
# Selected bearings and fractional origins must survive matrix/offset changes.
bearing_base=add(simple(square,[3]),800,120)
paired([component(bearing_base,1500,250,3|8|512,(.5,))],transformed(square,.5,0,0,.5,1500,250),[3],ref_advance=400,reference_points=transformed(square,.5,0,0,.5),reference_bearing=60)
paired([component(1,flags=35|512),component(2,-100,500)],square+transformed(curve,dx=-100,dy=500),[3,6],ref_advance=1000,reference_bearing=-100)
# Parent instructions can be flagged on a non-final component and are skipped safely.
paired([component(1,flags=35|256),component(1,1000,0)],square+transformed(square,dx=1000),[3,7],tail=u16(3)+b'abc')
# Empty components and wholly empty composites are valid.
paired([component(0)],[],[])
paired([component(0,flags=35),component(1)],square,[3])
invalid_records=[component(1,0,0,0),component(1)[:-2],component(65535),component(1,flags=3|8|64,matrix=(.5,.5)),component(1,flags=3|128,matrix=(1,0,0,1))[:-2],component(1,flags=3|256)+u16(6)+b'abc',component(1,flags=3|16)]
for data in invalid_records: failures.append((add(header(-1,(0,0,1000,1000))+data),'InvalidInput'))
# Invalid anchors versus unsupported phantom-point anchors.
failures.append((add(header(-1,(0,0,1000,1000))+base+component(1,100,0,1)),'InvalidInput'))
failures.append((add(header(-1,(0,0,1000,1000))+base+component(1,4,0,1)),'Unsupported'))
cycle=len(glyphs);failures.append((add(header(-1,(0,0,1000,1000))+component(cycle)),'InvalidInput'))
first=len(glyphs)
add(header(-1,(0,0,1000,1000))+component(first+1))
failures.append((add(header(-1,(0,0,1000,1000))+component(first)),'InvalidInput'))
previous=1
for _ in range(18): previous=add(header(-1,(0,0,1000,1000))+component(previous))
failures.append((previous,'Capacity'))
# Node budget also bounds wide graphs consisting only of empty components.
wide=header(-1,(0,0,0,0))+b''.join(component(0,flags=35 if i<256 else 3) for i in range(257))
failures.append((add(wide),'Capacity'))
# Point budget is shared by every leaf in a composite.
many=add(simple(square*1024,[i*4+3 for i in range(1024)]))
failures.append((add(header(-1,(0,0,1000,1000))+component(many,flags=35)+component(many,flags=35)+component(many)),'Capacity'))
# Rejected rotated metric selection, whose behavior OpenType leaves undefined.
failures.append((add(header(-1,(0,0,1000,1000))+component(1,1000,0,3|128|512,(0,1,-1,0))),'Unsupported'))
def fixture():
    head=bytearray(54);head[12:16]=u32(0x5f0f3cf5);head[18:20]=u16(1000);head[50:52]=u16(1)
    hhea=bytearray(36);hhea[4:10]=i16(1000)+i16(-200)+i16(0);hhea[34:36]=u16(len(glyphs))
    offsets=[0]
    for glyph in glyphs: offsets.append(offsets[-1]+len(glyph))
    cmap=u16(0)+u16(1)+u16(3)+u16(10)+u32(12)+u16(12)+u16(0)+u32(28)+u32(0)+u32(1)+u32(65)+u32(64+len(glyphs))+u32(0)
    tables={'head':bytes(head),'hhea':bytes(hhea),'maxp':u32(0x10000)+u16(len(glyphs)),'hmtx':b''.join(u16(a)+i16(b) for a,b in metrics),'loca':b''.join(u32(n) for n in offsets),'glyf':b''.join(glyphs),'cmap':cmap}
    offset=12+16*len(tables);directory=b'';body=b''
    for tag,data in tables.items(): directory+=tag.encode()+u32(0)+u32(offset)+u32(len(data));body+=data;offset+=len(data)
    return u32(0x10000)+u16(len(tables))+b'\0'*6+directory+body
SOURCE='''use "std/font" font
use "std/mem" mem
use "std/errors" errors
fn check(ok: bool) { if !ok { #panic("composite contract") } }
fn same(arena: *mem.Arena, face: *const font.Face, a, b: u16, size: u16) {
  mark := mem.arena_mark(arena)
  left := font.raster(arena, face, a, size)
  right := font.raster(arena, face, b, size)
  check(left.ok && right.ok)
  check(left.value.width == right.value.width && left.value.height == right.value.height)
  check(left.value.x_offset == right.value.x_offset && left.value.y_offset == right.value.y_offset && left.value.advance == right.value.advance)
  check(#len(left.value.pixels) == #len(right.value.pixels))
  for i in 0..#len(left.value.pixels) { check(left.value.pixels[i] == right.value.pixels[i]) }
  mem.arena_rewind(arena, mark)
}
fn main() {
  arena := mem.arena_create(0)
  defer { mem.arena_release(arena) }
  parsed := font.open(data[..])
  check(parsed.ok)
'''
for a,b in pairs:
    for size in (16,25): SOURCE+=f'  same(arena, &parsed.value, {a}, {b}, {size})\n'
for index,kind in failures:
    SOURCE+=f'  before_{index} := mem.arena_mark(arena)\n  check(font.raster(arena, &parsed.value, {index}, 16).kind == errors.Kind.{kind})\n  check(mem.arena_mark(arena) == before_{index})\n'
SOURCE+='}\n'
with tempfile.TemporaryDirectory(prefix='dyn-composite-results-') as directory:
    work=Path(directory);data=fixture()
    (work/'main.dyn').write_text('data: []const u8 = "'+''.join('\\x%02x'%byte for byte in data)+'"\n'+SOURCE)
    for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
        output=work/'program'
        subprocess.run([DYN,'build',str(work),*flags,'--quiet','--no-cache','--output',str(output)],check=True,timeout=300)
        subprocess.run([str(output)],check=True,timeout=120)
    for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows','wasm32-wasi'):
        output=work/target
        subprocess.run([DYN,'build',str(work),'--target',target,'--release','--opt-level','3','--quiet','--output',str(output)],check=True,timeout=300)
        emulator={'aarch64-linux':'qemu-aarch64','riscv64-linux':'qemu-riscv64','x86_64-windows':'wine'}.get(target)
        if emulator and shutil.which(emulator): subprocess.run([emulator,str(output)],check=True,timeout=120)
        if target=='wasm32-wasi' and shutil.which('node'):
            js="const {WASI}=require('node:wasi'),fs=require('node:fs');(async()=>{const wasi=new WASI({version:'preview1',returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});"
            subprocess.run(['node','--no-warnings','-e',js,str(output)],check=True,timeout=120)
print(f'PASS composites: {len(pairs)} flattened oracles at two sizes, {len(failures)} error/budget cases, rollback and cross-targets')
