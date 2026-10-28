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
SOURCE=r'''use "vendor/text/layout" layout
use "vendor/harfbuzz" hb
use "vendor/fribidi" bidi
use "std/mem" mem
use "std/fs" fs
use "std/dynlib" dynlib
use "std/errors" errors
use "std/encoding/binary" binary
fn check(ok:bool) {if !ok {#panic("shaped selection")}}
fn select(data:rawptr,text:[]const u8) layout.Face {return layout.Face{font:data,data:data}}
struct Range {start:usize,end:usize,path:[]const u8}
fn save(arena:*mem.Arena,rects:[]const layout.SelectionRect,path:[]const u8) {
 output:=mem.push_bytes_uninit(arena,4+#len(rects)*28)
 binary.store_u32_le(output[..4],#cast(u32,#len(rects)))
 for i in 0..#len(rects) {
  r:=rects[i]
  fields:[7]u32=[#cast(u32,r.line),#cast(u32,r.start),#cast(u32,r.end),#cast(u32,#cast(i32,r.x*64.0)),#cast(u32,#cast(i32,r.y*64.0)),#cast(u32,#cast(i32,r.width*64.0)),#cast(u32,#cast(i32,r.height*64.0))]
  for j in 0..7 {binary.store_u32_le(output[4+i*28+j*4..8+i*28+j*4],fields[j])}
 }
 check(fs.write_all(path,output).ok)
}
fn main() {
 owner:=mem.arena_create(0)
 scratch:=mem.arena_create(0)
 defer {mem.arena_release(scratch)
  mem.arena_release(owner)}
 library:=dynlib.open("HB_LIBRARY",dynlib.Now)
 bidi_library:=dynlib.open("BIDI_LIBRARY",dynlib.Now)
 check(library.ok && bidi_library.ok)
 defer {_=dynlib.close(&library.value)
  _=dynlib.close(&bidi_library.value)}
 h:=hb.load(library.value)
 b:=bidi.load(bidi_library.value)
 check(h.ok && b.ok)
 bytes:=fs.read_all(owner,"font.ttf",10000000)
 check(bytes.ok)
 font:=hb.font_owned(&h.api,bytes.value,0)
 check(font.ok)
 defer h.api.font_destroy(font.value)
 h.api.font_set_scale(font.value,2048,2048)
 descriptor:=layout.Font{data:font.value,select:select,line_height:40,space_advance:10.171875}
 CASES
 // Results own plain geometry even when the destination arena owns the layout.
 owned_layout:=layout.build(owner,"alias",descriptor,&h.api,&b.api,layout.Options{})
 check(owned_layout.ok)
 aliased:=layout.selection(owner,&owned_layout.value,0,5)
 check(aliased.ok && #len(aliased.value)==1 && aliased.value[0].x==0.0 && aliased.value[0].width==owned_layout.value.width)
 retained:=aliased.value[0]
 owned_layout.value.glyphs[0].x=123.0
 check(aliased.value[0].x==retained.x && aliased.value[0].width==retained.width && aliased.value[0].start==0 && aliased.value[0].end==5)
 // Public records can be forged; reject malformed slices before allocation.
 source:=layout.build(owner,"aéz",descriptor,&h.api,&b.api,layout.Options{})
 check(source.ok)
 mark:=mem.arena_mark(scratch)
 check(layout.selection(scratch,&source.value,2,3).kind==errors.Kind.InvalidInput)
 check(layout.selection(scratch,&source.value,0,2).kind==errors.Kind.InvalidInput)
 check(layout.selection(scratch,&source.value,4,3).kind==errors.Kind.InvalidInput)
 check(layout.selection(scratch,&source.value,0,5).kind==errors.Kind.InvalidInput)
 check(!layout.selection(scratch,nil,0,0).ok)
 check(!layout.selection(nil,&source.value,0,1).ok)
 check(mem.arena_mark(scratch)==mark)
 empty:=layout.selection(scratch,&source.value,1,1)
 check(empty.ok && #len(empty.value)==0 && mem.arena_mark(scratch)==mark)
 broken:=source.value
 broken.lines[0].glyph_count+=1
 check(layout.selection(scratch,&broken,0,1).kind==errors.Kind.InvalidInput && mem.arena_mark(scratch)==mark)
 broken.lines[0].glyph_count-=1
 // Newline bytes have no glyph cells; extension belongs to the editor.
 multiline:=layout.build(owner,"ab\n\nאב",descriptor,&h.api,&b.api,layout.Options{})
 check(multiline.ok)
 newline:=layout.selection(scratch,&multiline.value,2,4)
 check(newline.ok && #len(newline.value)==0 && mem.arena_mark(scratch)==mark)
 whole:=layout.selection(scratch,&multiline.value,0,#len(multiline.value.text))
 check(whole.ok && #len(whole.value)==2 && whole.value[0].line==0 && whole.value[1].line==2 && whole.value[1].y==80.0)
 mem.arena_reset(scratch)
 // Source cluster expansion includes ligature bytes and combining marks.
 ligature:=layout.build(owner,"office",descriptor,&h.api,&b.api,layout.Options{})
 check(ligature.ok)
 inside:=layout.selection(scratch,&ligature.value,2,3)
 check(inside.ok && #len(inside.value)==1 && inside.value[0].start==1 && inside.value[0].end==4)
 mem.arena_reset(scratch)
 marked:=layout.build(owner,"e\xcc\x81",descriptor,&h.api,&b.api,layout.Options{})
 check(marked.ok)
 accent:=layout.selection(scratch,&marked.value,1,3)
 check(accent.ok && #len(accent.value)==1 && accent.value[0].start==0 && accent.value[0].end==3)
 mem.arena_reset(scratch)
 // Non-contiguous visual cells retain their unselected bidi gap.
 mixed:=layout.build(owner,"abc אבג xyz",descriptor,&h.api,&b.api,layout.Options{})
 check(mixed.ok)
 split:=layout.selection(scratch,&mixed.value,2,6)
 check(split.ok && #len(split.value)==2 && split.value[0].x+split.value[0].width<split.value[1].x)
 mem.arena_reset(scratch)
 // Equal RTL parity does not imply visual adjacency: digits have level 2,
 // letters level 0, and their source-adjacent LTR cells flank unselected Hebrew.
 parity:=layout.build(owner,"abc אבג123def",descriptor,&h.api,&b.api,layout.Options{})
 check(parity.ok)
 parity_selection:=layout.selection(scratch,&parity.value,10,16)
 check(parity_selection.ok && #len(parity_selection.value)==2)
 check(parity_selection.value[0].x+parity_selection.value[0].width<parity_selection.value[1].x)
 check(parity_selection.value[0].start==10 && parity_selection.value[0].end==13 && parity_selection.value[1].start==13 && parity_selection.value[1].end==16)
 check(!layout.cluster_at(&parity.value,10).rtl && !layout.cluster_at(&parity.value,13).rtl)
 mem.arena_reset(scratch)
 // Long lines must remain linear in glyph count, including selection queries.
 long_bytes:=mem.push_bytes_uninit(owner,20000)
 for i in 0..#len(long_bytes) {long_bytes[i]=97}
 long_line:=layout.build(owner,long_bytes,descriptor,&h.api,&b.api,layout.Options{})
 check(long_line.ok)
 long_selection:=layout.selection(scratch,&long_line.value,1,19999)
 check(long_selection.ok && #len(long_selection.value)==1 && long_selection.value[0].start==1 && long_selection.value[0].end==19999)
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
        cases.append('if true {\nresult:=layout.build(owner,'+lit(text)+',descriptor,&h.api,&b.api,layout.Options{})\ncheck(result.ok)\nranges:['+str(len(ranges))+']Range=['+','.join(ranges)+']\nfor range in ranges {\nchosen:=layout.selection(scratch,&result.value,range.start,range.end)\ncheck(chosen.ok)\nsave(scratch,chosen.value,range.path)\nmem.arena_reset(scratch)\n}\n}')
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
