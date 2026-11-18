#!/usr/bin/env python3
"""Directional shaped layout against independent HarfBuzz/FriBidi C records."""
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
CASES=['office AV','السلام','אבג','abc سلام 123 (xyz)','אבג 123, abc!','A\tאבג\tB','a\u2067אב 12\u2069 z','e\u0301 שָׁלוֹם']
def lit(text): return '"'+''.join(f'\\x{x:02x}' for x in text.encode())+'"'
SOURCE=r'''use "vendor/text/layout" layout
use "vendor/harfbuzz" hb
use "vendor/fribidi" bidi
use "std/mem" mem
use "std/io"
use "std/fail"
use "std/fs" fs
use "std/dynlib" dynlib
use "std/io" errors
use "std/bytes" bytes
use "std/unicode/utf8" utf8
use "std/encoding/binary" binary
struct layout_build_Outcome { value: layout.Layout, failure: fail.Failure, kind: fail.Kind }
fn layout_build(a0: *mem.Arena, p0:[]const u8, p1:layout.Font, p2:*const hb.Api, p3:*const bidi.Api, p4:layout.Options) layout_build_Outcome {
  status: fail.Status
  value := layout.build(a0, &status, p0, p1, p2, p3, p4)
  return layout_build_Outcome{ value: value, failure: status.failure, kind: status.failure.kind }
}

struct hb_font_owned_Outcome { value: rawptr, failure: fail.Failure, kind: fail.Kind }
fn hb_font_owned(p0: *const hb.Api, p1: []const u8, p2: u32) hb_font_owned_Outcome {
  status: fail.Status
  value := hb.font_owned(&status, p0, p1, p2)
  return hb_font_owned_Outcome{ value: value, failure: status.failure, kind: status.failure.kind }
}

struct hb_load_Outcome { api: hb.Api, failure: fail.Failure, kind: fail.Kind }
fn hb_load(p0: dynlib.Handle) hb_load_Outcome {
  status: fail.Status
  value := hb.load(&status, p0)
  return hb_load_Outcome{ api: value, failure: status.failure, kind: status.failure.kind }
}

struct bidi_load_Outcome { api: bidi.Api, failure: fail.Failure, kind: fail.Kind }
fn bidi_load(p0: dynlib.Handle) bidi_load_Outcome {
  status: fail.Status
  value := bidi.load(&status, p0)
  return bidi_load_Outcome{ api: value, failure: status.failure, kind: status.failure.kind }
}

struct dynlib_open_Outcome { value: dynlib.Handle, failure: fail.Failure, kind: fail.Kind }
fn dynlib_open(p0: []const u8, p1: i32) dynlib_open_Outcome {
  status: fail.Status
  value := dynlib.open(&status, p0, p1)
  return dynlib_open_Outcome{ value: value, failure: status.failure, kind: status.failure.kind }
}

struct dynlib_close_Outcome { failure: fail.Failure, kind: fail.Kind }
fn dynlib_close(p0: *dynlib.Handle) dynlib_close_Outcome {
  status: fail.Status
  dynlib.close(&status, p0)
  return dynlib_close_Outcome{ failure: status.failure, kind: status.failure.kind }
}

fn failed(failure: fail.Failure) bool {
  return failure.kind != fail.Kind.Ok
}

fn check(ok:bool) {if !ok {#panic("shaped text layout")}}
fn select(data:rawptr,text:[]const u8) layout.Face {return layout.Face{font:data,data:data}}
other_font:rawptr
fn context_select(data:rawptr,text:[]const u8) layout.Face {
 if utf8.decode(text,0).codepoint==1580 {return layout.Face{font:other_font,data:other_font}}
 return layout.Face{font:data,data:data}
}
fn reject(data:rawptr,text:[]const u8) layout.Face {return layout.Face{}}
fn save(arena:*mem.Arena,result:*const layout.Layout,path:[]const u8) {
 out:=mem.push_bytes_uninit(arena,4+#len(result.glyphs)*32)
 binary.store_u32_le(out[..4],#cast(u32,#len(result.glyphs)))
 for i in 0..#len(result.glyphs) {
  g:=result.glyphs[i]
  values:[8]u32=[g.id,#cast(u32,g.start),#cast(u32,g.end),#cast(u32,#cast(i32,g.x*64.0)),#cast(u32,#cast(i32,g.y*64.0)),#cast(u32,#cast(i32,g.x_offset*64.0)),#cast(u32,#cast(i32,g.y_offset*64.0)),#cast(u32,#cast(i32,g.advance*64.0))]
  for j in 0..8 {binary.store_u32_le(out[4+i*32+j*4..8+i*32+j*4],values[j])}
 }
 check(fs_write_file(path,out))
}
fn main() {
 arena:=mem.arena_alloc(0)
 defer mem.arena_release(arena)
 hb_library:=dynlib_open("HB_LIBRARY",dynlib.Now)
 bidi_library:=dynlib_open("BIDI_LIBRARY",dynlib.Now)
 check(!failed(hb_library.failure) && !failed(bidi_library.failure))
 defer {_=dynlib_close(&hb_library.value)
  _=dynlib_close(&bidi_library.value)}
 h:=hb_load(hb_library.value)
 b:=bidi_load(bidi_library.value)
 check(!failed(h.failure) && !failed(b.failure))
 data_file: fail.Status
 data := fs.read_all(arena, &data_file, "font.ttf", 10000000)
 check(!data_file.failed)
 created:=hb_font_owned(&h.api,data,0)
 check(!failed(created.failure))
 defer h.api.font_destroy(created.value)
 h.api.font_set_scale(created.value,2048,2048)
 font:=layout.Font{data:created.value,select:select,line_height:40,space_advance:10.171875}
 other:=hb_font_owned(&h.api,data,0)
 check(!failed(other.failure))
 other_font=other.value
 defer h.api.font_destroy(other.value)
 h.api.font_set_scale(other.value,2048,2048)
 fallback:=layout_build(arena,"بجح",layout.Font{data:created.value,select:context_select,line_height:40,space_advance:10.171875},&h.api,&b.api,layout.Options{})
 check(!failed(fallback.failure) && #len(fallback.value.glyphs)==3)
 save(arena,&fallback.value,"actual-fallback.bin")
 CASES
 empty:=layout_build(arena,"",font,&h.api,&b.api,layout.Options{})
 check(!failed(empty.failure) && #len(empty.value.lines)==1 && #len(empty.value.glyphs)==0 && empty.value.height==40.0)
 eof:=layout.cluster_at(&empty.value,0)
 check(eof.found && eof.start==0 && eof.end==0)
 multiline:=layout_build(arena,"a\r\n\nאבג\xe2\x80\xa8z",font,&h.api,&b.api,layout.Options{})
 check(!failed(multiline.failure) && #len(multiline.value.lines)==4 && multiline.value.lines[1].start==3 && multiline.value.lines[2].start==4)
 rtl:=layout_build(arena,"אבג",font,&h.api,&b.api,layout.Options{})
 check(!failed(rtl.failure) && rtl.value.glyphs[0].start>rtl.value.glyphs[#len(rtl.value.glyphs)-1].start)
 left:=layout.at_point(&rtl.value,-10.0,0.0)
 right:=layout.at_point(&rtl.value,10000.0,0.0)
 check(left.found && right.found && right.start==0 && right.end==0)
 mark:=mem.arena_mark(arena)
 check(layout_build(arena,"\xff",font,&h.api,&b.api,layout.Options{}).kind==fail.Kind.InvalidInput && mem.arena_mark(arena)==mark)
 check(layout_build(arena,"x",layout.Font{select:reject,line_height:40,space_advance:10.0},&h.api,&b.api,layout.Options{}).kind==fail.Kind.NotFound && mem.arena_mark(arena)==mark)
 wrapped:=layout_build(arena,"office office السلام abc אבג",font,&h.api,&b.api,layout.Options{width:65})
 check(!failed(wrapped.failure) && #len(wrapped.value.lines)>1)
 for line in wrapped.value.lines {
  if line.width>65.0 {check(line.glyph_count>0)
   first:=wrapped.value.glyphs[line.glyph_start]
   for i in line.glyph_start..line.glyph_start+line.glyph_count {check(wrapped.value.glyphs[i].start==first.start)}
  }
 }
 for g in wrapped.value.glyphs {check(g.start<g.end && g.end<=#len(wrapped.value.text))
  hit:=layout.cluster_at(&wrapped.value,g.start)
  check(hit.found && hit.start==g.start && hit.end==g.end)
 }
 check(!layout.cluster_at(&wrapped.value,#len(wrapped.value.text)+1).found)
 alias:=layout_build(arena,wrapped.value.text,font,&h.api,&b.api,layout.Options{})
 check(!failed(alias.failure) && bytes.equal(alias.value.text,wrapped.value.text))
 // A long unwrapped editor line must not perform a source scan per glyph.
 long_text:=mem.push_bytes_uninit(arena,20000)
 for i in 0..#len(long_text) {long_text[i]=120}
 long_line:=layout_build(arena,long_text,font,&h.api,&b.api,layout.Options{})
 check(!failed(long_line.failure) && #len(long_line.value.glyphs)==20000 && #len(long_line.value.lines)==1)
 long_hit:=layout.at_point(&long_line.value,long_line.value.width-1.0,0.0)
 check(long_hit.found && long_hit.start==19999)
 missing:=layout_build(arena,"कर्म",font,&h.api,&b.api,layout.Options{width:5})
 check(!failed(missing.failure))
 for g in missing.value.glyphs {check(g.start<g.end && g.end<=12)}
 dash:=layout_build(arena,"-",font,&h.api,&b.api,layout.Options{})
 soft:=layout_build(arena,"ab\xc2\xadcd",font,&h.api,&b.api,layout.Options{width:55})
 check(!failed(dash.failure) && !failed(soft.failure) && #len(soft.value.lines)==2)
 soft_line:=soft.value.lines[0]
 soft_glyph:=soft.value.glyphs[soft_line.glyph_start+soft_line.glyph_count-1]
 check(soft_glyph.id==dash.value.glyphs[0].id && soft_glyph.start==2 && soft_glyph.end==4)
 mixed:=layout_build(arena,"abc אבג",font,&h.api,&b.api,layout.Options{})
 check(!failed(mixed.failure))
 mixed_eof:=layout.cluster_at(&mixed.value,#len(mixed.value.text))
 check(mixed_eof.found && mixed_eof.rtl && mixed_eof.x<mixed.value.width)

}

// Writes data to path; whether it worked.
fn fs_write_file(path: []const u8, data: []const u8) bool {
  status: fail.Status
  fs.write_all(&status, path, data)
  return !status.failed
}
'''
# C deliberately items scalars, applies native bidi line reordering, then shapes
# directional/script runs without using the Dyn layout implementation.
C=r'''#include <hb.h>
#include <hb-ot.h>
#include <fribidi.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static void u(FILE*f,uint32_t n){for(int i=0;i<4;i++)fputc((n>>(i*8))&255,f);}
struct Run {int start,end,first,last,level,fallback;hb_script_t script;hb_glyph_info_t *infos;hb_glyph_position_t *positions;unsigned count;};
int main(int argc,char**argv){
 if(argc!=4&&argc!=5)return 2;int fallback_mode=argc==5;FILE*font_file=fopen(argv[1],"rb");if(!font_file)return 3;fseek(font_file,0,SEEK_END);long size=ftell(font_file);rewind(font_file);char*data=malloc(size);if(fread(data,1,size,font_file)!=(size_t)size)return 4;fclose(font_file);
 hb_blob_t*blob=hb_blob_create(data,size,HB_MEMORY_MODE_DUPLICATE,NULL,NULL);hb_face_t*face=hb_face_create(blob,0);hb_font_t*font=hb_font_create(face);hb_ot_font_set_funcs(font);hb_font_set_scale(font,2048,2048);hb_font_t*other=hb_font_create(face);hb_ot_font_set_funcs(other);hb_font_set_scale(other,2048,2048);
 FILE*input=fopen(argv[2],"rb");fseek(input,0,SEEK_END);long length=ftell(input);rewind(input);char*text=calloc(length+1,1);if(fread(text,1,length,input)!=(size_t)length)return 5;fclose(input);
 FriBidiChar*cp=calloc(length+1,sizeof(*cp));int n=fribidi_charset_to_unicode(FRIBIDI_CHAR_SET_UTF8,text,length,cp);int*starts=calloc(n+1,sizeof(int));int at=0;for(int i=0;i<n;i++){starts[i]=at;unsigned c=(unsigned char)text[at++];while(c>=0xc0 && at<length && ((unsigned char)text[at]&0xc0)==0x80)at++;}starts[n]=length;
 FriBidiLevel*levels=calloc(n+1,sizeof(*levels));FriBidiCharType*types=calloc(n+1,sizeof(*types));FriBidiParType base=FRIBIDI_PAR_ON;fribidi_get_bidi_types(cp,n,types);if(n&&!fribidi_log2vis(cp,n,&base,NULL,NULL,NULL,levels))return 6;
 FriBidiStrIndex*map=calloc(n+1,sizeof(*map));for(int i=0;i<n;i++)map[i]=i;if(n&&!fribidi_reorder_line(0,types,n,0,base,levels,NULL,map))return 7;
 hb_script_t*scripts=calloc(n+1,sizeof(*scripts));hb_script_t previous=HB_SCRIPT_INVALID;for(int i=0;i<n;i++){hb_script_t s=hb_unicode_script(hb_unicode_funcs_get_default(),cp[i]);if(s!=HB_SCRIPT_COMMON && s!=HB_SCRIPT_INHERITED && s!=HB_SCRIPT_INVALID)previous=s;else s=previous;scripts[i]=s;}hb_script_t next=HB_SCRIPT_INVALID;for(int i=n-1;i>=0;i--){if(scripts[i]!=HB_SCRIPT_INVALID && scripts[i]!=HB_SCRIPT_COMMON && scripts[i]!=HB_SCRIPT_INHERITED)next=scripts[i];else scripts[i]=next;}
 struct Run*runs=calloc(n+1,sizeof(*runs));int nr=0;for(int i=0;i<n;){struct Run*r=&runs[nr++];r->first=i;r->start=starts[i];r->level=levels[i];r->script=scripts[i];r->fallback=fallback_mode&&cp[i]==1580;i++;while(i<n && (fallback_mode&&cp[i]==1580)==r->fallback && cp[i]!=9 && cp[r->first]!=9 && levels[i]==r->level && scripts[i]==r->script)i++;r->last=i;r->end=starts[i];if(cp[r->first]==9)continue;hb_buffer_t*b=hb_buffer_create();hb_buffer_add_utf8(b,text,length,r->start,r->end-r->start);hb_buffer_set_direction(b,r->level&1?HB_DIRECTION_RTL:HB_DIRECTION_LTR);hb_buffer_set_script(b,r->script);hb_buffer_set_cluster_level(b,HB_BUFFER_CLUSTER_LEVEL_MONOTONE_GRAPHEMES);hb_buffer_set_flags(b,(r->first==0?HB_BUFFER_FLAG_BOT:0)|(r->last==n?HB_BUFFER_FLAG_EOT:0));hb_buffer_guess_segment_properties(b);hb_shape(r->fallback?other:font,b,NULL,0);unsigned count=0;hb_glyph_info_t*infos=hb_buffer_get_glyph_infos(b,&count);hb_glyph_position_t*pos=hb_buffer_get_glyph_positions(b,&count);r->count=count;r->infos=malloc(count*sizeof(*infos));r->positions=malloc(count*sizeof(*pos));memcpy(r->infos,infos,count*sizeof(*infos));for(unsigned k=0;k<count;k++)r->infos[k].cluster-=r->start;memcpy(r->positions,pos,count*sizeof(*pos));hb_buffer_destroy(b);}
 int*order=calloc(nr+1,sizeof(int));int*seen=calloc(nr+1,sizeof(int));int used=0;for(int i=0;i<n;i++)for(int r=0;r<nr;r++)if(!seen[r]&&map[i]>=runs[r].first&&map[i]<runs[r].last){seen[r]=1;order[used++]=r;break;}
 unsigned total=0;for(int r=0;r<nr;r++)total+=cp[runs[r].first]==9?1:runs[r].count;FILE*out=fopen(argv[3],"wb");u(out,total);int x=0;for(int o=0;o<used;o++){struct Run*r=&runs[order[o]];if(cp[r->first]==9){int tab=2604;int advance=(x/tab+1)*tab-x;u(out,0);u(out,r->start);u(out,r->end);u(out,x);u(out,0);u(out,0);u(out,0);u(out,advance);x+=advance;continue;}unsigned i=0;int previous_end=r->end;while(i<r->count){unsigned next=i+1;while(next<r->count&&r->infos[next].cluster==r->infos[i].cluster)next++;int start=r->start+r->infos[i].cluster;int end=(r->level&1)?previous_end:next<r->count?r->start+r->infos[next].cluster:r->end;for(unsigned j=i;j<next;j++){u(out,r->infos[j].codepoint);u(out,start);u(out,end);u(out,x);u(out,0);u(out,r->positions[j].x_offset);u(out,-r->positions[j].y_offset);u(out,r->positions[j].x_advance);x+=r->positions[j].x_advance;}previous_end=start;i=next;}}
 fclose(out);hb_font_destroy(other);hb_font_destroy(font);hb_face_destroy(face);hb_blob_destroy(blob);free(data);return 0;
}
'''
if not shutil.which('cc') or not shutil.which('pkg-config') or subprocess.run(['pkg-config','--exists','harfbuzz','fribidi']).returncode:
    print('SKIP shaped layout: native HarfBuzz/FriBidi development packages unavailable')
    raise SystemExit(0)
font=next((p for p in [Path('/usr/share/fonts/TTF/DejaVuSans.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')] if p.exists()),None)
if font is None:
    print('SKIP shaped layout: DejaVuSans fixture unavailable')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-shaped-layout-') as directory:
    work=Path(directory)
    shutil.copyfile(font,work/'font.ttf')
    (work/'oracle.c').write_text(C)
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','harfbuzz','fribidi'],text=True))
    subprocess.run(['cc','-std=c11','-O2',str(work/'oracle.c'),*flags,'-o',str(work/'oracle')],check=True)
    (work/'fallback.txt').write_text('بجح',encoding='utf-8')
    subprocess.run([str(work/'oracle'),'font.ttf','fallback.txt','expected-fallback.bin','fallback'],cwd=work,check=True)
    cases=[]
    for i,text in enumerate(CASES):
        (work/f'case-{i}.txt').write_text(text,encoding='utf-8')
        subprocess.run([str(work/'oracle'),'font.ttf',f'case-{i}.txt',f'expected-{i}.bin'],cwd=work,check=True)
        cases.append(f'result_{i}:=layout_build(arena,{lit(text)},font,&h.api,&b.api,layout.Options{{}})\ncheck(!failed(result_{i}.failure))\nsave(arena,&result_{i}.value,"actual-{i}.bin")')
    source=SOURCE.replace('CASES','\n'.join(cases)).replace('HB_LIBRARY',ctypes.util.find_library('harfbuzz') or 'libharfbuzz.so.0').replace('BIDI_LIBRARY',ctypes.util.find_library('fribidi') or 'libfribidi.so.0')
    (work/'main.dyn').write_text(source,encoding='utf-8')
    for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
        binary=work/'test'
        subprocess.run([DYN,'build',str(work),*flags,'--quiet','--output',str(binary)],check=True,timeout=180)
        subprocess.run([str(binary)],cwd=work,check=True,timeout=20)
        assert (work/'actual-fallback.bin').read_bytes()==(work/'expected-fallback.bin').read_bytes(), 'fallback font boundaries retain joining context'
        for i in range(len(CASES)):
            actual=(work/f'actual-{i}.bin').read_bytes();expected=(work/f'expected-{i}.bin').read_bytes()
            if actual!=expected:
                values=lambda data: [struct.unpack('<8i',data[n:n+32]) for n in range(4,len(data),32)]
                raise AssertionError((CASES[i],values(actual),values(expected)))
    for target in ['aarch64-linux','riscv64-linux','x86_64-windows','aarch64-windows','x86_64-macos','aarch64-macos']:
        subprocess.run([DYN,'build',str(work),'--release','--target',target,'--emit-object','--no-link','--quiet','--output',str(work/target)],check=True,timeout=180)
print('PASS shaped layout: independent HB/FriBidi glyph IDs/clusters/visual positions, Unicode source offsets, wrapping, lines/hits and atomic errors (debug/O2/O3; six desktop objects)')
