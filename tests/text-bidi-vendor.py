#!/usr/bin/env python3
"""FriBidi fixed C ABI and copied paragraph/line results against C oracle."""
import ctypes.util
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
CASES=[('',64),('plain Latin 123',64),('سلام',64),('אבג',64),('abc سلام 123 (xyz)',64),('אבג 123, abc!',64),('  123 - (45)  ',64),('abc אבג   xyz',273),('אבג abc   ',273),('a\u2067אב 12\u2069 z',64),('a\u202e123\u202c b',64),('שָׁלוֹם café 😀',64),('A\tאבג\tB',272),('A\0אבג',64)]
def lit(data): return '"'+''.join(f'\\x{x:02x}' for x in data)+'"'
SOURCE=r'''use "vendor/fribidi" bidi
use "std/dynlib" dynlib
use "std/mem" mem
use "std/fs" fs
use "std/encoding/binary" binary
use "std/errors" errors
fn check(ok:bool) { if !ok { #panic("FriBidi binding contract") } }
fn append(out:[]u8,at:*usize,value:u32) {
 binary.store_u32_le(out[at.*..at.*+4],value)
 at.*+=4
}
fn save(arena:*mem.Arena,api:*const bidi.Api,text:[]const u8,base:u32,path:[]const u8) {
 result:=bidi.resolve(arena,api,text,base)
 check(result.ok)
 p:=result.value
 n:=#len(p.logical)
 out:=mem.push_bytes_uninit(arena,8+n*32+4*(4+n*8))
 at:usize=0
 append(out,&at,#cast(u32,n))
 append(out,&at,p.base)
 for i in 0..n {
  append(out,&at,p.logical[i])
  append(out,&at,p.visual[i])
  append(out,&at,#cast(u32,p.starts[i]))
  append(out,&at,#cast(u32,p.ends[i]))
  append(out,&at,#cast(u32,p.logical_to_visual[i]))
  append(out,&at,#cast(u32,p.visual_to_logical[i]))
  append(out,&at,#cast(u32,p.levels[i]))
  append(out,&at,p.types[i])
 }
 starts:[4]usize=[0,0,n/2,0]
 ends:[4]usize=[n,n/2,n,n]
 if n>=3 {starts[3]=n-3}
 for k in 0..4 {
  line:=bidi.reorder(arena,api,&p,starts[k],ends[k])
  check(line.ok)
  append(out,&at,#cast(u32,#len(line.value.levels)))
  for i in 0..#len(line.value.levels) {
   append(out,&at,#cast(u32,line.value.visual_to_logical[i]))
   append(out,&at,#cast(u32,line.value.levels[i]))
  }
 }
 check(fs.write_all(path,out[..at]).ok)
}
fn fail_resolve(input:*const u32,n:i32,base:*u32,visual:*u32,lv:*i32,vl:*i32,levels:*i8) i8 {
 _=input
 _=n
 _=base
 _=visual
 _=lv
 _=vl
 _=levels
 return 0
}
fn fail_reorder(flags:u32,types:*const u32,n,off:i32,base:u32,levels:*i8,visual:*u32,map:*i32) i8 {
 _=flags
 _=types
 _=n
 _=off
 _=base
 _=levels
 _=visual
 _=map
 return 0
}
fn main() {
 arena:=mem.Arena{}
 defer mem.arena_release(&arena)
 library:=dynlib.open("LIBRARY",dynlib.Now)
 check(library.ok)
 loaded:=bidi.load(library.value)
 check(loaded.ok)
 api:=loaded.api
 CASE_CALLS
 mark:=mem.arena_mark(&arena)
 check(!bidi.resolve(&arena,&api,"\xc0\xaf",bidi.Auto).ok && mem.arena_mark(&arena)==mark)
 check(!bidi.resolve(&arena,&api,"a\nb",bidi.Auto).ok && mem.arena_mark(&arena)==mark)
 check(!bidi.resolve(&arena,&api,"a\xe2\x80\xa9b",bidi.Auto).ok && mem.arena_mark(&arena)==mark)
 check(!bidi.resolve(&arena,&api,"abc",123).ok && mem.arena_mark(&arena)==mark)
 check(!bidi.load(nil).ok)
 nil_api:=bidi.Api{}
 check(bidi.resolve(&arena,&nil_api,"",bidi.Auto).ok)
 check(bidi.resolve(&arena,&nil_api,"a",bidi.Auto).kind==errors.Kind.InvalidState && mem.arena_mark(&arena)==mark)
 broken:=api
 broken.log2vis=fail_resolve
 check(bidi.resolve(&arena,&broken,"abc",bidi.Auto).kind==errors.Kind.System && mem.arena_mark(&arena)==mark)
 source:[4]u8=[97,215,144,98]
 owned:=bidi.resolve(&arena,&api,source[..],bidi.Auto)
 check(owned.ok && owned.value.logical[1]==1488 && owned.value.starts[1]==1 && owned.value.ends[1]==3)
 source[1]=120
 paragraph:=owned.value
 saved_level:=paragraph.levels[1]
 line:=bidi.reorder(&arena,&api,&paragraph,0,2)
 check(line.ok && paragraph.levels[1]==saved_level)
 mark=mem.arena_mark(&arena)
 check(!bidi.reorder(&arena,&api,&paragraph,2,1).ok && mem.arena_mark(&arena)==mark)
 check(!bidi.reorder(&arena,&api,&paragraph,0,4).ok && mem.arena_mark(&arena)==mark)
 broken=api
 broken.reorder_line=fail_reorder
 check(bidi.reorder(&arena,&broken,&paragraph,0,2).kind==errors.Kind.System && mem.arena_mark(&arena)==mark)
 check(dynlib.close(&library.value).ok)
 check(paragraph.logical[1]==1488 && paragraph.starts[1]==1 && paragraph.ends[1]==3 && paragraph.levels[1]==saved_level)
}
'''
C=r'''#include <fribidi.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
_Static_assert(sizeof(FriBidiChar)==4 && sizeof(FriBidiParType)==4 && sizeof(FriBidiStrIndex)==4 && sizeof(FriBidiLevel)==1,"FriBidi public ABI");
_Static_assert(FRIBIDI_PAR_ON==64 && FRIBIDI_PAR_LTR==272 && FRIBIDI_PAR_RTL==273,"FriBidi directions");
static void word(FILE*f,uint32_t x){if(fwrite(&x,4,1,f)!=1)abort();}
static void save(const FriBidiChar*input,const uint32_t*starts,const uint32_t*ends,int n,FriBidiParType base,const char*path){
 FriBidiChar visual[256]={0};FriBidiStrIndex lv[256]={0},vl[256]={0};FriBidiLevel levels[256]={0};FriBidiCharType types[256]={0};
 if(n && !fribidi_log2vis(input,n,&base,visual,lv,vl,levels))abort();
 fribidi_get_bidi_types(input,n,types);
 FILE*f=fopen(path,"wb");if(!f)abort();word(f,(uint32_t)n);word(f,base);
 for(int i=0;i<n;i++){word(f,input[i]);word(f,visual[i]);word(f,starts[i]);word(f,ends[i]);word(f,(uint32_t)lv[i]);word(f,(uint32_t)vl[i]);word(f,(uint32_t)levels[i]);word(f,types[i]);}
 int first[4]={0,0,n/2,n>=3?n-3:0};int last[4]={n,n/2,n,n};
 for(int k=0;k<4;k++){
  FriBidiLevel copy[256];FriBidiStrIndex map[256];memcpy(copy,levels,sizeof(copy));for(int i=0;i<n;i++)map[i]=i;
  int count=last[k]-first[k];if(count && !fribidi_reorder_line(0,types,count,first[k],base,copy,NULL,map))abort();
  word(f,(uint32_t)count);for(int i=first[k];i<last[k];i++){word(f,(uint32_t)map[i]);word(f,(uint32_t)copy[i]);}
 }
 fclose(f);
}
int main(void){CASE_CALLS return 0;}
'''
if not shutil.which('cc') or not shutil.which('pkg-config') or subprocess.run(['pkg-config','--exists','fribidi']).returncode:
 print('SKIP FriBidi native oracle: development library unavailable');raise SystemExit(0)
library=ctypes.util.find_library('fribidi')
if not library: raise SystemExit('FriBidi runtime unavailable despite development package')
with tempfile.TemporaryDirectory(prefix='dyn-fribidi-') as directory:
 work=Path(directory)
 calls=[];c_calls=[]
 for i,(text,base) in enumerate(CASES):
  starts=[];ends=[];offset=0
  for cp in text: starts.append(offset);offset+=len(cp.encode());ends.append(offset)
  calls.append(f'save(&arena,&api,{lit(text.encode())},{base},"{work}/dyn-{i}")')
  def array(values):return '{'+','.join(map(str,values or [0]))+'}'
  c_calls.append(f'{{const FriBidiChar input[]={array(list(map(ord,text)))};const uint32_t starts[]={array(starts)},ends[]={array(ends)};save(input,starts,ends,{len(text)},{base},"{work}/c-{i}");}}')
 source=SOURCE.replace('LIBRARY',library).replace('CASE_CALLS','\n'.join(calls))
 (work/'main.dyn').write_text(source)
 (work/'oracle.c').write_text(C.replace('CASE_CALLS','\n'.join(c_calls)))
 flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','fribidi'],text=True))
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(work/'oracle.c'),*flags,'-o',str(work/'oracle')],check=True)
 subprocess.run([str(work/'oracle')],check=True)
 for build_flags in (['--debug'],['--release'],['--release','--opt-level','3']):
  output=work/'test'
  subprocess.run([DYN,'build',str(work),*build_flags,'--quiet','--output',str(output)],check=True,timeout=180)
  subprocess.run([str(output)],check=True,timeout=60)
  for i in range(len(CASES)):
   actual=(work/f'dyn-{i}').read_bytes();expected=(work/f'c-{i}').read_bytes()
   assert actual==expected,(CASES[i],build_flags,actual.hex(),expected.hex())
 for target in ('aarch64-linux','riscv64-linux','x86_64-windows','aarch64-windows','x86_64-macos','aarch64-macos'):
  subprocess.run([DYN,'build',str(work),'--release','--target',target,'--emit-object','--no-link','--quiet','--output',str(work/target)],check=True,timeout=180)
print('PASS FriBidi: C ABI, mixed scripts/numbers/controls, UTF8 source ranges, line L1/L2 maps, copied ownership and atomic failures (debug/O2/O3; six desktop object targets)')
