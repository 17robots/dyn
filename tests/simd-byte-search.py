#!/usr/bin/env python3
"""Artifact-only trusted byte search: C oracle, bounded loads, effects and FP."""
import os,platform,re,shlex,shutil,subprocess,tempfile
from pathlib import Path
HERE=Path(__file__).resolve()
roots=[p for p in HERE.parents if (p/'src/ir.h').is_file() and (p/'std/bytes/bytes.dyn').is_file()]
if not roots:
 print('SKIP SIMD search: compiler source root unavailable')
 raise SystemExit(0)
ROOT=next((p for p in roots if (p/'std').resolve().parent==p.resolve()),roots[0])
name=os.environ.get('DYN',str(ROOT/'build/dyn-release'))
found=shutil.which(name)
if not found:
 print('SKIP SIMD search: compiler unavailable: '+name)
 raise SystemExit(0)
DYN=Path(found).resolve()
ENV=dict(os.environ,DYN_SDK=os.environ.get('DYN_SDK',str(ROOT)))
CC=shlex.split(os.environ.get('CC','cc'))
CLANG=shlex.split(os.environ.get('CLANG','clang'))
OBJDUMP=shutil.which('objdump') or shutil.which('llvm-objdump')
SOURCE=r'''
use "std/bytes" bytes
use "std/io"
extern fn oracle() i32
pub fn search(source:[]const u8,needle:u8) usize { return bytes.find_byte(source,needle) }
pub fn substring(source:[]const u8,needle:[]const u8) usize { return bytes.find(source,needle) }
pub fn substring_indirect(source:[]const u8,needle:[]const u8) usize { f:=bytes.find
return f(source,needle) }
pub fn substring_floating(source:[]const u8,needle:[]const u8,a,b,c,d,e,f,g,h:f64) f64 {
 at:=bytes.find(source,needle)
 return a+b*2.0+c*3.0+d*4.0+e*5.0+f*6.0+g*7.0+h*8.0+#cast(f64,at)
}
pub fn substring_bits(source:[]const u8,needle:[]const u8,a,b,c,d,e,f,g,h:u64) u64 {
 at:=bytes.find(source,needle)
 return a^b^c^d^e^f^g^h^#cast(u64,at)
}
pub fn indirect(source:[]const u8,needle:u8) usize {
 f:=bytes.find_byte
 return f(source,needle)
}
pub fn floating(source:[]const u8,needle:u8,a,b,c,d,e,f,g,h:f64) f64 {
 at:=bytes.find_byte(source,needle)
 return a+b*2.0+c*3.0+d*4.0+e*5.0+f*6.0+g*7.0+h*8.0+#cast(f64,at)
}
pub fn bits_live(source:[]const u8,needle:u8,a,b,c,d,e,f,g,h:u64) u64 {
 at:=bytes.find_byte(source,needle)
 return a^b^c^d^e^f^g^h^#cast(u64,at)
}
pub fn mutation() usize {
 data:[64]u8=[]
 data[20]=7
 first:=bytes.find_byte(data[..],7)
 data[20]=0
 data[37]=7
 second:=bytes.find_byte(data[..],7)
 data[37]=0
 data[52]=7
 needle:[1]u8=[7]
 third:=bytes.find(data[..],needle[..])
 data[52]=0
 data[53]=7
 fourth:=bytes.find(data[..],needle[..])
 return first+second*100+third*10000+fourth*1000000
}
fn main() { if mutation()!=53523720 { #panic("search memory effects") }
result:=oracle()
if result!=0 { _=io.println(io.stderr(),"oracle {}",result)
#panic("SSE byte oracle") } }
'''
C=r'''
#include <stdint.h>
#include <stddef.h>
static long call6(long n,long a,long b,long c,long d,long e,long f) {
 register long r10 __asm__("r10")=d;register long r8 __asm__("r8")=e;register long r9 __asm__("r9")=f;
 long r;__asm__ volatile("syscall":"=a"(r):"a"(n),"D"(a),"S"(b),"d"(c),"r"(r10),"r"(r8),"r"(r9):"rcx","r11","memory");return r;
}
extern uint64_t search(const uint8_t*,uint64_t,uint8_t),indirect(const uint8_t*,uint64_t,uint8_t);
extern double floating(const uint8_t*,uint64_t,uint8_t,double,double,double,double,double,double,double,double);
extern uint64_t bits_live(const uint8_t*,uint64_t,uint8_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t);
static uint64_t scalar(const uint8_t*p,uint64_t n,uint8_t c) { for(uint64_t i=0;i<n;i++) if(p[i]==c)return i;return n; }
static int substring_oracle(void);
int32_t oracle(void) {
 uint8_t *map=(void*)call6(9,0,4096*3,0,0x22,-1,0);
 if((intptr_t)map<0 || call6(10,(long)(map+4096),4096,3,0,0,0))return 90;
 uint8_t *data=map+4096;
 if(search(0,0,255)!=0 || search(map,0,0)!=0)return 1;
 for(unsigned needle=0;needle<256;needle++)for(unsigned n=0;n<=129;n++)for(unsigned alignment=0;alignment<18;alignment++) {
  uint8_t *p=alignment==0?data:alignment==1?data+4096-n:data+256+alignment;
  for(unsigned i=0;i<n;i++)p[i]=(uint8_t)(needle^128);
  if(search(p,n,(uint8_t)needle)!=n)return 2;
  if(n) {
   unsigned indices[4]={n-1,n/2,0,n/2};
   for(unsigned j=0;j<4;j++) {
    p[indices[j]]=(uint8_t)needle;
    if(search(p,n,(uint8_t)needle)!=scalar(p,n,(uint8_t)needle))return 3;
   }
  }
 }
 uint8_t small[65];for(unsigned i=0;i<65;i++)small[i]=3;small[37]=4;
 if(indirect(small,65,4)!=37)return 4;
 double x=floating(small,65,4,1.25,2.5,3.75,5.0,6.25,7.5,8.75,10.0);
 if(x!=255.0+37.0)return 5;
 if(bits_live(small,65,4,1,2,4,8,16,32,64,128)!=(255^37))return 6;
 call6(11,(long)map,4096*3,0,0,0,0);return substring_oracle();
}

extern uint64_t substring(const uint8_t*,uint64_t,const uint8_t*,uint64_t),substring_indirect(const uint8_t*,uint64_t,const uint8_t*,uint64_t);
extern double substring_floating(const uint8_t*,uint64_t,const uint8_t*,uint64_t,double,double,double,double,double,double,double,double);
extern uint64_t substring_bits(const uint8_t*,uint64_t,const uint8_t*,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t);
static uint64_t reference(const uint8_t*h,uint64_t n,const uint8_t*p,uint64_t m) {
 if(!m)return 0;if(m>n)return n;
 for(uint64_t i=0;i<=n-m;i++){uint64_t j=0;while(j<m && h[i+j]==p[j])j++;if(j==m)return i;}return n;
}
static uint32_t random_state=0x817fbe29;
static uint8_t random_byte(void) { random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;return (uint8_t)random_state; }
static int substring_oracle(void) {
 uint8_t *hm=(void*)call6(9,0,4096*3,0,0x22,-1,0),*nm=(void*)call6(9,0,4096*3,0,0x22,-1,0);
 if((intptr_t)hm<0 || (intptr_t)nm<0 || call6(10,(long)(hm+4096),4096,3,0,0,0) || call6(10,(long)(nm+4096),4096,3,0,0,0))return 91;
 uint8_t *hay=hm+4096,*needle=nm+4096;
 if(substring(0,0,0,0)!=0 || substring(hm,0,nm,0)!=0 || substring(hm,0,needle,1)!=0)return 11;
 for(unsigned n=0;n<=257;n++)for(unsigned m=0;m<=40;m++)for(unsigned alignment=0;alignment<18;alignment++) {
  uint8_t *h=alignment==0?hay:alignment==1?hay+4096-n:hay+256+alignment;
  uint8_t *p=alignment==0?needle:alignment==1?needle+4096-m:needle+256+(alignment*7)%16;
  for(unsigned pattern=0;pattern<3;pattern++) {
   for(unsigned i=0;i<n;i++)h[i]=pattern==0?random_byte():0xaa;
   for(unsigned i=0;i<m;i++)p[i]=pattern==0?random_byte():0xaa;
   if(pattern==1 && m)p[0]=0xbb; /* every last-byte candidate rejects its prefix */
   if(pattern==2 && m)p[m-1]=0xbb;
   if(substring(h,n,p,m)!=reference(h,n,p,m))return 12;
   if(m && m<=n) {
    unsigned at=pattern==0?(n-m)/2:n-m;
    for(unsigned i=0;i<m;i++)h[at+i]=p[i];
    if(substring(h,n,p,m)!=reference(h,n,p,m))return 13;
   }
  }
 }
 for(unsigned period=1;period<=7;period++)for(unsigned m=1;m<=40;m++)for(unsigned n=40;n<=257;n++) {
  for(unsigned i=0;i<n;i++)hay[i]=(uint8_t)(i%period);
  for(unsigned i=0;i<m;i++)needle[i]=(uint8_t)((i+1)%period);
  if(substring(hay,n,needle,m)!=reference(hay,n,needle,m))return 18;
 }
 for(unsigned byte=0;byte<256;byte++)for(unsigned m=1;m<=40;m++) {
  for(unsigned i=0;i<257;i++)hay[i]=(uint8_t)(byte^128);
  for(unsigned i=0;i<m;i++)needle[i]=(uint8_t)byte;
  for(unsigned i=0;i<m;i++)hay[257-m+i]=needle[i];
  if(substring(hay,257,needle,m)!=257-m)return 14;
 }
 for(unsigned i=0;i<65;i++)hay[i]=3;hay[37]=4;needle[0]=4;
 if(substring_indirect(hay,65,needle,1)!=37)return 15;
 if(substring_floating(hay,65,needle,1,1.25,2.5,3.75,5.0,6.25,7.5,8.75,10.0)!=292.0)return 16;
 if(substring_bits(hay,65,needle,1,1,2,4,8,16,32,64,128)!=(255^37))return 17;
 call6(11,(long)hm,4096*3,0,0,0,0);call6(11,(long)nm,4096*3,0,0,0,0);return 0;
}

'''
# Argument effects/guards still run before the search; pending cleanup belongs
# to the caller. Nonempty null C-ABI slices violate the existing precondition.
FAIL=r'''
use "std/bytes" bytes
use "std/io"
extern fn drive() i32
observed:usize
fn source_effect(source:[]const u8) []const u8 { observed=observed*10+1
return source }
fn needle_effect() u8 { observed=observed*10+2
return 0 }
pub fn protected(source:[]const u8) {
 defer { _=io.println(io.stdout(),"cleanup {}",observed) }
 _=bytes.find_byte(source_effect(source),needle_effect())
 observed+=100
}
fn main() { _=drive() }
'''
def run(args,**kw):
 try:
  return subprocess.run([str(x) for x in args],check=True,timeout=120,**kw)
 except subprocess.CalledProcessError as error:
  if error.stdout: print(error.stdout)
  if error.stderr: print(error.stderr)
  raise

def inspect(output,target):
 if not OBJDUMP:
  print('SKIP '+target+' SIMD opcode inspection: objdump unavailable')
  return
 asm=run([OBJDUMP,'-dr','-Mintel',str(output)+'.o'],capture_output=True,text=True).stdout
 for name,callee in [('search','find_byte'),('substring','find')]:
  body=re.search(r'<'+name+r'>:\n(.*?)(?=\n\n|\Z)',asm,re.S).group(1)
  assert all(op in body for op in ['movdqu','pcmpeqb','pmovmskb','bsf']),body
  assert not re.search(r'R_(?:X86_64|AMD64)_\w+\s+'+callee+r'(?:-|\b)',body),body
  # Artifact diagnostics stay in the temporary output directory; durable tests
  # never write assembly files alongside repository test sources.
  (output.parent/(target+'-'+name+'.asm')).write_text(body)

def build(project,output,oracle,mode,target=None):
 env=dict(ENV,DYN_NO_SSA='1' if mode=='tree' else '0')
 command=[DYN,'build',project,'--release','--opt-level','3','--no-cache','--opt-remarks','--emit-object','--link',oracle,'--output',output]
 if target:command+=['--target',target]
 result=run(command,env=env,capture_output=True,text=True)
 if mode=='ssa':
  for name in ['search','substring','mutation']:
   assert re.search(r'remark: '+name+r': SSA code generation',result.stderr),result.stderr
  inspect(output,target or 'x86_64-linux')
 return env

def linux_proof(w):
 project=w/'source';project.mkdir();(project/'main.dyn').write_text(SOURCE);(w/'oracle.c').write_text(C)
 run([*CC,'-std=c11','-O2','-fno-stack-protector','-ffreestanding','-c',w/'oracle.c','-o',w/'oracle.o'])
 for mode in ['ssa','tree']:
  output=w/mode
  env=build(project,output,w/'oracle.o',mode)
  run([output],env=env)
 for operation in ['find_byte','find']:
  for label in ['empty','invalid','effects','argument-panic']:
   source=FAIL
   if operation=='find':
    source=source.replace('fn needle_effect() u8 { observed=observed*10+2\nreturn 0 }', 'fn needle_effect() []const u8 { observed=observed*10+2\nreturn "x" }').replace('bytes.find_byte(source_effect(source),needle_effect())','bytes.find(source_effect(source),needle_effect())')
   if label=='argument-panic':source=source.replace('observed=observed*10+2\nreturn 0','observed=observed*10+2\np:*u8=nil\nreturn p.*').replace('observed=observed*10+2\nreturn "x"','observed=observed*10+2\np:*u8=nil\nvalue:=p.*\n_=value\nreturn "x"')
   (project/'main.dyn').write_text(source)
   pointer='data' if label in ('effects','argument-panic') else '0'
   length=0 if label=='empty' else 1
   (w/'forged.c').write_text('extern void protected(const char*,unsigned long); int drive(void) { static const char data[]={1};protected('+pointer+','+str(length)+');return 0;}')
   run([*CC,'-O2','-fno-stack-protector','-ffreestanding','-c',w/'forged.c','-o',w/'forged.o'])
   for mode in ['ssa','tree']:
    output=w/f'{operation}-{label}-{mode}';env=dict(ENV,DYN_NO_SSA='1' if mode=='tree' else '0')
    run([DYN,'build',project,'--release','--opt-level','3','--no-cache','--link',w/'forged.o','--output',output],env=env,capture_output=True,text=True)
    result=subprocess.run([str(output)],text=True,capture_output=True,timeout=20,env=env)
    if label=='invalid': assert result.returncode<0,result
    elif label=='argument-panic':
     assert result.returncode!=0 and result.stdout=='cleanup 12\n',result
     assert 'pointer.nonnull.ok' in result.stderr and ' in needle_effect\n' in result.stderr,result
    else:assert result.returncode==0 and result.stdout=='cleanup 112\n',result
 print('PASS Linux SIMD search: guarded C oracle, effects, argument checks and cleanup')

def windows_proof(w):
 project=w/'source';project.mkdir();(project/'main.dyn').write_text(SOURCE)
 # The same independent C oracle uses Windows-provided guarded pages. Avoid
 # host libc/headers/libraries beyond Clang's freestanding standard headers.
 start=C.index('static long call6(');end=C.index('\nextern uint64_t search',start)
 adapter='''extern void *dyn_win_virtual_alloc(void*,uint64_t,uint32_t,uint32_t);extern int32_t dyn_win_virtual_free(void*,uint64_t,uint32_t);
static long long call6(long long n,long long a,long long b,long long c,long long d,long long e,long long f) {
 (void)b;(void)c;(void)d;(void)e;(void)f;
 if(n==9)return (long long)dyn_win_virtual_alloc(0,12288,0x2000,1);
 if(n==10)return dyn_win_virtual_alloc((void*)a,4096,0x1000,4)?0:-1;
 if(n==11){dyn_win_virtual_free((void*)a,0,0x8000);return 0;}return -1;
}'''
 portable=C[:start]+adapter+C[end:]
 # Windows LLP64 has 32-bit long, so pointer carriers are explicitly 64-bit.
 portable=re.sub(r'(?<!long )\blong\b(?! long)', 'long long',portable)
 (w/'oracle.c').write_text(portable)
 result=subprocess.run([*CLANG,'--target=x86_64-pc-windows-msvc','-std=c11','-O2','-fno-stack-protector','-ffreestanding','-c',str(w/'oracle.c'),'-o',str(w/'oracle.o')],capture_output=True,text=True,timeout=120)
 if result.returncode:
  print('SKIP Win64 oracle: Clang cannot emit freestanding COFF: '+result.stderr.strip())
  return
 runner=[] if os.name=='nt' else [shutil.which('wine')]
 for mode in ['ssa','tree']:
  output=w/(mode+'.exe');env=build(project,output,w/'oracle.o',mode,'x86_64-windows')
  if runner and not runner[0]:
   print('SKIP Win64 '+mode+' runtime: Wine unavailable (cross-build passed)')
   continue
  run([*runner,output],env=dict(env,WINEDEBUG='-all'),capture_output=True,text=True)
  print('PASS Win64 '+mode+': guarded C oracle, scratch registers, live FP/GPR and memory effects')

with tempfile.TemporaryDirectory(prefix='dyn-simd-search-') as directory:
 work=Path(directory)
 if platform.system()=='Linux' and platform.machine().lower() in ('x86_64','amd64'):
  if CC and shutil.which(CC[0]):
   linux=work/'linux';linux.mkdir();linux_proof(linux)
  else:print('SKIP Linux SIMD search: C compiler unavailable')
 else:print('SKIP Linux raw-syscall guard oracle: requires x86-64 Linux')
 if CLANG and shutil.which(CLANG[0]):
  windows=work/'windows';windows.mkdir();windows_proof(windows)
 else:print('SKIP Win64 cross-build/runtime: Clang unavailable')
