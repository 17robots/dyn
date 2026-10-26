#!/usr/bin/env python3
"""Private trusted JSON scanner: all bytes, odd slices, guarded ends and fallback."""
from pathlib import Path
import os,platform,re,shutil,subprocess,tempfile
R=Path(__file__).resolve().parents[1]
D=Path(os.environ.get('DYN',R/'build/dyn-release')).resolve()
if platform.system()!='Linux' or platform.machine() not in ('x86_64','amd64'):
 print('SKIP JSON ASCII prefix: Linux x64 execution fixture');raise SystemExit(0)
def run(args,**kwargs):
 p=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=120,**kwargs)
 assert p.returncode==0,(args,p.stdout,p.stderr)
 return p
SOURCE='''use "std/encoding/json/read" json
extern fn oracle() i32
pub fn prefix(source:[]const u8) usize { return json.test_prefix(source) }
pub fn floating(source:[]const u8,a,b,c,d,e,f,g,h:f64) f64 {
 at:=json.test_prefix(source)
 return a+b*2.0+c*3.0+d*4.0+e*5.0+f*6.0+g*7.0+h*8.0+#cast(f64,at)
}
fn main(){ if oracle()!=0 { #panic("JSON ASCII prefix oracle") } }
'''
C=r'''
#include <stdint.h>
#include <stddef.h>
static long call6(long n,long a,long b,long c,long d,long e,long f){
 register long r10 __asm__("r10")=d;register long r8 __asm__("r8")=e;register long r9 __asm__("r9")=f;
 long r;__asm__ volatile("syscall":"=a"(r):"a"(n),"D"(a),"S"(b),"d"(c),"r"(r10),"r"(r8),"r"(r9):"rcx","r11","memory");return r;
}
extern size_t prefix(const uint8_t*,size_t);
extern double floating(const uint8_t*,size_t,double,double,double,double,double,double,double,double);
static size_t expected(const uint8_t*p,size_t n){for(size_t i=0;i<n;i++)if(p[i]<32||p[i]>=128||p[i]==34||p[i]==92)return i;return n;}
int oracle(void){
 uint8_t*map=(void*)call6(9,0,12288,0,0x22,-1,0);
 if((intptr_t)map<0||call6(10,(long)(map+4096),4096,3,0,0,0))return 90;
 if(prefix(0,0)!=0||prefix(map,0)!=0)return 1;
 for(size_t n=0;n<=129;n++)for(size_t pad=0;pad<17;pad++)for(unsigned byte=0;byte<256;byte++){
  uint8_t*p=map+4096+pad;
  for(size_t i=0;i<n;i++)p[i]='a';
  if(n)p[n/2]=(uint8_t)byte;
  if(prefix(p,n)!=expected(p,n))return 2;
  if(floating(p,n,1,2,3,4,5,6,7,8)!=204+(double)expected(p,n))return 3;
 }
 for(size_t n=0;n<=129;n++)for(unsigned byte=0;byte<256;byte++){
  uint8_t*p=map+8192-n;
  for(size_t i=0;i<n;i++)p[i]='a';
  if(n)p[n-1]=(uint8_t)byte;
  if(prefix(p,n)!=expected(p,n))return 4;
 }
 call6(11,(long)map,12288,0,0,0,0);return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-json-prefix-') as tmp:
 w=Path(tmp);sdk=w/'sdk';shutil.copytree(R/'std',sdk/'std')
 module=sdk/'std/encoding/json/read/read.dyn'
 with module.open('a') as f:f.write('\npub fn test_prefix(source:[]const u8) usize { return ascii_string_prefix(source) }\n')
 project=w/'project';project.mkdir();(project/'main.dyn').write_text(SOURCE)
 (w/'oracle.c').write_text(C)
 run([os.environ.get('CC','cc'),'-O2','-ffreestanding','-fno-stack-protector','-c',w/'oracle.c','-o',w/'oracle.o'])
 for mode in ('ssa','tree'):
  env=dict(os.environ,DYN_SDK=str(sdk),DYN_NO_SSA='0' if mode=='ssa' else '1')
  binary=w/mode
  run([D,'build',project,'--release','--opt-level','3','--no-cache','--emit-object','--link',w/'oracle.o','--output',binary],env=env)
  run([binary])
  asm=run(['objdump','-d','-Mintel',str(binary)+'.o']).stdout
  # Existing decoder has no SIMD byte comparison in scalar mode.
  assert ('pcmpgtb' in asm)==(mode=='ssa'),mode
  print('PASS private JSON ASCII prefix '+mode+': byte/length/alignment, guarded tail, FP live values')
 # Same helper spelling and signature outside the SDK must keep its body.
 fake=project/'fake';fake.mkdir();(fake/'fake.dyn').write_text('fn ascii_string_prefix(source:[]const u8) usize { return 7 }\npub fn test(source:[]const u8) usize { return ascii_string_prefix(source) }\n')
 (project/'main.dyn').write_text('use "fake" fake\nfn main(){ if fake.test("abc")!=7 { #panic("untrusted helper") } }\n')
 run([D,'build',project,'--release','--opt-level','3','--no-cache','--output',w/'fake'],env=dict(os.environ,DYN_SDK=str(sdk)))
 run([w/'fake'])
 print('PASS private JSON ASCII prefix provenance: local lookalike keeps ordinary behavior')
