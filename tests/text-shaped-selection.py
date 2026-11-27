#!/usr/bin/env python3
"""Visual selection unions derived from independent C HarfBuzz/FriBidi glyphs."""
import ast
import ctypes.util
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
CASES=['office AV','abc אבג123def','abc אבג xyz','אבג 123, abc!','abc سلام 123 (xyz)','e\u0301 שָׁלוֹם','A\tאבג\tB','a\u2067אב 12\u2069 z']
def lit(text): return '"'+''.join(f'\\x{x:02x}' for x in text.encode())+'"'
SOURCE=r'''use layout "vendor/text/layout"
use hb "vendor/harfbuzz"
use bidi "vendor/fribidi"
use mem "std/mem"
use "std/io"
use fs "std/fs"
use dynlib "std/dynlib"
use errors "std/io"
use binary "std/encoding/binary"
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
struct Failure { kind: Kind, native: isize }
fn failure_of(err: io.IoErr) Failure {
  case err {
    .System(code) => { return Failure{ kind: Kind.System, native: code } }
    _ => { return Failure{ kind: kind_of(err) } }
  }
}
struct layout_build_Outcome { value: layout.Layout, failure: Failure, kind: Kind }
fn layout_build(a0: *mem.Arena, p0:[]const u8, p1:layout.Font, p2:*const hb.Api, p3:*const bidi.Api, p4:layout.Options) layout_build_Outcome {
  value := layout.build(a0, p0, p1, p2, p3, p4) catch err {
    failure := failure_of(err)
    return layout_build_Outcome{ failure: failure, kind: failure.kind }
  }
  return layout_build_Outcome{ value: value }
}

struct layout_selection_Outcome { value: []layout.SelectionRect, failure: Failure, kind: Kind }
fn layout_selection(a0: *mem.Arena, p0: *const layout.Layout, p1, p2: usize) layout_selection_Outcome {
  value := layout.selection(a0, p0, p1, p2) catch err {
    failure := failure_of(err)
    return layout_selection_Outcome{ failure: failure, kind: failure.kind }
  }
  return layout_selection_Outcome{ value: value }
}

struct hb_font_owned_Outcome { value: rawptr, failure: Failure, kind: Kind }
fn hb_font_owned(p0: *const hb.Api, p1: []const u8, p2: u32) hb_font_owned_Outcome {
  value := hb.font_owned(p0, p1, p2) catch err {
    failure := failure_of(err)
    return hb_font_owned_Outcome{ failure: failure, kind: failure.kind }
  }
  return hb_font_owned_Outcome{ value: value }
}

struct hb_load_Outcome { api: hb.Api, failure: Failure, kind: Kind }
fn hb_load(p0: dynlib.Handle) hb_load_Outcome {
  value := hb.load(p0) catch err {
    failure := failure_of(err)
    return hb_load_Outcome{ failure: failure, kind: failure.kind }
  }
  return hb_load_Outcome{ api: value }
}

struct bidi_load_Outcome { api: bidi.Api, failure: Failure, kind: Kind }
fn bidi_load(p0: dynlib.Handle) bidi_load_Outcome {
  value := bidi.load(p0) catch err {
    failure := failure_of(err)
    return bidi_load_Outcome{ failure: failure, kind: failure.kind }
  }
  return bidi_load_Outcome{ api: value }
}

struct dynlib_open_Outcome { value: dynlib.Handle, failure: Failure, kind: Kind }
fn dynlib_open(p0: []const u8, p1: i32) dynlib_open_Outcome {
  value := dynlib.open(p0, p1) catch err {
    failure := failure_of(err)
    return dynlib_open_Outcome{ failure: failure, kind: failure.kind }
  }
  return dynlib_open_Outcome{ value: value }
}

struct dynlib_close_Outcome { failure: Failure, kind: Kind }
fn dynlib_close(p0: *dynlib.Handle) dynlib_close_Outcome {
  dynlib.close(p0) catch err {
    failure := failure_of(err)
    return dynlib_close_Outcome{ failure: failure, kind: failure.kind }
  }
  return dynlib_close_Outcome{}
}

fn failed(failure: Failure) bool {
  return failure.kind != Kind.Ok
}

fn check(ok:bool) {if !ok {#panic("shaped selection")}}
fn select(data:rawptr,text:[]const u8) layout.Face {return layout.Face{font:data,data:data}}
struct Range {start:usize,end:usize,path:[]const u8}
fn save(arena:*mem.Arena,rects:[]const layout.SelectionRect,path:[]const u8) {
 output:=mem.push_bytes(arena,4+rects.len*28)
 binary.store_u32_le(output[..4],#cast(u32,rects.len))
 for i in 0..rects.len {
  r:=rects[i]
  fields:[7]u32=[#cast(u32,r.line),#cast(u32,r.start),#cast(u32,r.end),#cast(u32,#cast(i32,r.x*64.0)),#cast(u32,#cast(i32,r.y*64.0)),#cast(u32,#cast(i32,r.width*64.0)),#cast(u32,#cast(i32,r.height*64.0))]
  for j in 0..7 {binary.store_u32_le(output[4+i*28+j*4..8+i*28+j*4],fields[j])}
 }
 check(fs_write_file(path,output))
}
fn main() {
 owner:=mem.arena_alloc(0)
 scratch:=mem.arena_alloc(0)
 defer {mem.arena_release(scratch)
  mem.arena_release(owner)}
 library:=dynlib_open("HB_LIBRARY",dynlib.Now)
 bidi_library:=dynlib_open("BIDI_LIBRARY",dynlib.Now)
 check(!failed(library.failure) && !failed(bidi_library.failure))
 defer {_=dynlib_close(&library.value)
  _=dynlib_close(&bidi_library.value)}
 h:=hb_load(library.value)
 b:=bidi_load(bidi_library.value)
 check(!failed(h.failure) && !failed(b.failure))
 bytes := fs.read_all(owner, "font.ttf", 10000000) catch { #panic("cannot read a fixture") }
 font:=hb_font_owned(&h.api,bytes,0)
 check(!failed(font.failure))
 defer h.api.font_destroy(font.value)
 h.api.font_set_scale(font.value,2048,2048)
 descriptor:=layout.Font{data:font.value,select:select,line_height:40,space_advance:10.171875}
 CASES
 // Results own plain geometry even when the destination arena owns the layout.
 owned_layout:=layout_build(owner,"alias",descriptor,&h.api,&b.api,layout.Options{})
 check(!failed(owned_layout.failure))
 aliased:=layout_selection(owner,&owned_layout.value,0,5)
 check(!failed(aliased.failure) && aliased.value.len==1 && aliased.value[0].x==0.0 && aliased.value[0].width==owned_layout.value.width)
 retained:=aliased.value[0]
 owned_layout.value.glyphs[0].x=123.0
 check(aliased.value[0].x==retained.x && aliased.value[0].width==retained.width && aliased.value[0].start==0 && aliased.value[0].end==5)
 // Public records can be forged; reject malformed slices before allocation.
 source:=layout_build(owner,"aéz",descriptor,&h.api,&b.api,layout.Options{})
 check(!failed(source.failure))
 mark:=mem.arena_mark(scratch)
 check(layout_selection(scratch,&source.value,2,3).kind==Kind.InvalidInput)
 check(layout_selection(scratch,&source.value,0,2).kind==Kind.InvalidInput)
 check(layout_selection(scratch,&source.value,4,3).kind==Kind.InvalidInput)
 check(layout_selection(scratch,&source.value,0,5).kind==Kind.InvalidInput)
 check(failed(layout_selection(scratch,nil,0,0).failure))
 check(failed(layout_selection(nil,&source.value,0,1).failure))
 check(mem.arena_mark(scratch)==mark)
 empty:=layout_selection(scratch,&source.value,1,1)
 check(!failed(empty.failure) && empty.value.len==0 && mem.arena_mark(scratch)==mark)
 broken:=source.value
 broken.lines[0].glyph_count+=1
 check(layout_selection(scratch,&broken,0,1).kind==Kind.InvalidInput && mem.arena_mark(scratch)==mark)
 broken.lines[0].glyph_count-=1
 // Newline bytes have no glyph cells; extension belongs to the editor.
 multiline:=layout_build(owner,"ab\n\nאב",descriptor,&h.api,&b.api,layout.Options{})
 check(!failed(multiline.failure))
 newline:=layout_selection(scratch,&multiline.value,2,4)
 check(!failed(newline.failure) && newline.value.len==0 && mem.arena_mark(scratch)==mark)
 whole:=layout_selection(scratch,&multiline.value,0,multiline.value.text.len)
 check(!failed(whole.failure) && whole.value.len==2 && whole.value[0].line==0 && whole.value[1].line==2 && whole.value[1].y==80.0)
 mem.arena_reset(scratch)
 // Source cluster expansion includes ligature bytes and combining marks.
 ligature:=layout_build(owner,"office",descriptor,&h.api,&b.api,layout.Options{})
 check(!failed(ligature.failure))
 inside:=layout_selection(scratch,&ligature.value,2,3)
 check(!failed(inside.failure) && inside.value.len==1 && inside.value[0].start==1 && inside.value[0].end==4)
 mem.arena_reset(scratch)
 marked:=layout_build(owner,"e\xcc\x81",descriptor,&h.api,&b.api,layout.Options{})
 check(!failed(marked.failure))
 accent:=layout_selection(scratch,&marked.value,1,3)
 check(!failed(accent.failure) && accent.value.len==1 && accent.value[0].start==0 && accent.value[0].end==3)
 mem.arena_reset(scratch)
 // Non-contiguous visual cells retain their unselected bidi gap.
 mixed:=layout_build(owner,"abc אבג xyz",descriptor,&h.api,&b.api,layout.Options{})
 check(!failed(mixed.failure))
 split:=layout_selection(scratch,&mixed.value,2,6)
 check(!failed(split.failure) && split.value.len==2 && split.value[0].x+split.value[0].width<split.value[1].x)
 mem.arena_reset(scratch)
 // Equal RTL parity does not imply visual adjacency: digits have level 2,
 // letters level 0, and their source-adjacent LTR cells flank unselected Hebrew.
 parity:=layout_build(owner,"abc אבג123def",descriptor,&h.api,&b.api,layout.Options{})
 check(!failed(parity.failure))
 parity_selection:=layout_selection(scratch,&parity.value,10,16)
 check(!failed(parity_selection.failure) && parity_selection.value.len==2)
 check(parity_selection.value[0].x+parity_selection.value[0].width<parity_selection.value[1].x)
 check(parity_selection.value[0].start==10 && parity_selection.value[0].end==13 && parity_selection.value[1].start==13 && parity_selection.value[1].end==16)
 first_cluster:=layout.cluster_at(&parity.value,10) catch { #panic("cluster_at") }
 second_cluster:=layout.cluster_at(&parity.value,13) catch { #panic("cluster_at") }
 check(!first_cluster.rtl && !second_cluster.rtl)
 mem.arena_reset(scratch)
 // Long lines must remain linear in glyph count, including selection queries.
 long_bytes:=mem.push_bytes(owner,20000)
 for i in 0..long_bytes.len {long_bytes[i]=97}
 long_line:=layout_build(owner,long_bytes,descriptor,&h.api,&b.api,layout.Options{})
 check(!failed(long_line.failure))
 long_selection:=layout_selection(scratch,&long_line.value,1,19999)
 check(!failed(long_selection.failure) && long_selection.value.len==1 && long_selection.value[0].start==1 && long_selection.value[0].end==19999)
}

// Writes data to path; whether it worked.
fn fs_write_file(path: []const u8, data: []const u8) bool {
  fs.write_all(path, data) catch { return false }
  return true
}
'''
# Reuse only the independent C shaping oracle, never its Dyn implementation.
parsed=ast.parse((ROOT/'tests/text-shaped-vendor.py').read_text())
C=next(ast.literal_eval(n.value) for n in parsed.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='C' for t in n.targets))
def expected(records,start,end):
    clusters={}
    for _,low,high,x,_,_,_,advance in records:
        key=(low,high)
        left,right=sorted((x,x+advance))
        if key in clusters:
            old=clusters[key];clusters[key]=(min(old[0],left),max(old[1],right))
        else:clusters[key]=(left,right)
    cells=sorted((left,right,low,high) for (low,high),(left,right) in clusters.items() if low<end and high>start and right>left) if start!=end else []
    unions=[]
    for left,right,low,high in cells:
        if unions and left<=unions[-1][1]:
            previous=unions[-1]
            unions[-1]=(previous[0],max(previous[1],right),min(previous[2],low),max(previous[3],high))
        else:unions.append((left,right,low,high))
    return struct.pack('<I',len(unions))+b''.join(struct.pack('<7i',0,low,high,left,0,right-left,40*64) for left,right,low,high in unions)
if not shutil.which('cc') or not shutil.which('pkg-config') or subprocess.run(['pkg-config','--exists','harfbuzz','fribidi']).returncode:
    print('SKIP shaped selection: HarfBuzz/FriBidi development packages unavailable');raise SystemExit(0)
font=next((p for p in [Path('/usr/share/fonts/TTF/DejaVuSans.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')] if p.exists()),None)
if font is None:
    print('SKIP shaped selection: DejaVuSans fixture unavailable');raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-shaped-selection-') as directory:
    work=Path(directory);shutil.copyfile(font,work/'font.ttf');(work/'oracle.c').write_text(C)
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','harfbuzz','fribidi'],text=True))
    subprocess.run(['cc','-std=c11','-O2',str(work/'oracle.c'),*flags,'-o',str(work/'oracle')],check=True)
    cases=[];paths=[]
    for index,text in enumerate(CASES):
        (work/f'text-{index}').write_text(text,encoding='utf-8')
        subprocess.run([str(work/'oracle'),'font.ttf',f'text-{index}',f'glyphs-{index}'],cwd=work,check=True)
        glyphs=(work/f'glyphs-{index}').read_bytes();records=[struct.unpack('<8i',glyphs[i:i+32]) for i in range(4,len(glyphs),32)]
        offsets=[0]
        for char in text:offsets.append(offsets[-1]+len(char.encode()))
        ranges=[]
        for low in offsets:
            for high in offsets:
                if high<low:continue
                path=f'case-{index}-{low}-{high}.bin';paths.append(path)
                (work/('expected-'+path)).write_bytes(expected(records,low,high))
                ranges.append(f'Range{{start:{low},end:{high},path:"{path}"}}')
        cases.append('if true {\nresult:=layout_build(owner,'+lit(text)+',descriptor,&h.api,&b.api,layout.Options{})\ncheck(!failed(result.failure))\nranges:['+str(len(ranges))+']Range=['+','.join(ranges)+']\nfor range in ranges {\nchosen:=layout_selection(scratch,&result.value,range.start,range.end)\ncheck(!failed(chosen.failure))\nsave(scratch,chosen.value,range.path)\nmem.arena_reset(scratch)\n}\n}')
    source=SOURCE.replace('CASES','\n'.join(cases)).replace('HB_LIBRARY',ctypes.util.find_library('harfbuzz') or 'libharfbuzz.so.0').replace('BIDI_LIBRARY',ctypes.util.find_library('fribidi') or 'libfribidi.so.0')
    (work/'main.dyn').write_text(source,encoding='utf-8')
    for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
        output=work/'test';subprocess.run([DYN,'build',str(work),*flags,'--quiet','--output',str(output)],check=True,timeout=180)
        subprocess.run([str(output)],cwd=work,check=True,timeout=20)
        for path in paths:
            actual=(work/path).read_bytes();wanted=(work/('expected-'+path)).read_bytes()
            if actual!=wanted:
                unpack=lambda data:[struct.unpack('<7i',data[i:i+28]) for i in range(4,len(data),28)]
                raise AssertionError((path,unpack(actual),unpack(wanted)))
    for target in ['aarch64-linux','riscv64-linux','x86_64-windows','aarch64-windows','x86_64-macos','aarch64-macos']:
        subprocess.run([DYN,'build',str(work),'--release','--target',target,'--emit-object','--no-link','--quiet','--output',str(work/target)],check=True,timeout=180)
print('PASS shaped selection: independent C glyph unions, mixed bidi gaps, ligatures/marks/tabs, multiline source ranges, atomic errors and 20k-line linearity (debug/O2/O3; six desktop objects)')
