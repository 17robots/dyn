#!/usr/bin/env python3
"""Exact small x86 zero extents, guard pages and aggregate lowering controls."""
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
if platform.system() != 'Linux' or platform.machine() != 'x86_64':
    print('SKIP small zero fill: requires x86-64 Linux')
    raise SystemExit(0)

# Compile the actual emitter function with a minimal byte sink. Execute its
# bytes against an independent bytewise oracle, including inaccessible zero
# destinations. No source-language pointer checks hide boundary overwrites.
isa = (ROOT/'src/backend/isa.inc').read_text()
start = isa.index('static void isa_zero_fill(')
emitter = isa[start:isa.index('\n}\n', start)+3]
HARNESS = r'''
#define _GNU_SOURCE
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
typedef struct { bool t32,rv32,rv64,a64; unsigned char code[4096]; size_t n; } BackendContext;
static void byte(BackendContext *ctx,unsigned char b) { ctx->code[ctx->n++]=b; }
static void word(BackendContext *ctx,uint32_t n) { for(unsigned i=0;i<4;i++) byte(ctx,(unsigned char)(n>>(8*i))); }
#define CODE(...) do { const unsigned char code[]={__VA_ARGS__}; for(size_t j=0;j<sizeof code;j++) byte(ctx,code[j]); } while(0)
#define t32_zero_fill(...) abort()
#define r32_zero_fill(...) abort()
#define rv_imm(...) abort()
#define rv_move(...) abort()
#define rv_compare(...) abort()
#define rv_branch(...) (abort(),(size_t)0)
#define rv_memory(...) abort()
#define rv_i(...) abort()
#define rv_patch(c,a,b) do { (void)(c); (void)(a); (void)(b); abort(); } while(0)
#define a64_immediate(...) abort()
#define a64_word(...) abort()
'''
# The unreachable RV branch references ctx->text.n; give the minimal sink an
# alias rather than importing unrelated backend infrastructure.
HARNESS = HARNESS.replace('size_t n; } BackendContext;', 'size_t n; struct { size_t n; } text; } BackendContext;')
HARNESS += emitter + r'''
int main(void) {
 size_t page=(size_t)sysconf(_SC_PAGESIZE);
 unsigned char *map=mmap(0,page*3,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
 unsigned char *code=mmap(0,page,PROT_READ|PROT_WRITE|PROT_EXEC,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
 if(map==MAP_FAILED || code==MAP_FAILED || mprotect(map+page,page,PROT_READ|PROT_WRITE)) return 90;
 unsigned char *data=map+page;
 for(unsigned size=0;size<=129;size++) {
  BackendContext ctx={0}; byte(&ctx,0x48);byte(&ctx,0x89);byte(&ctx,0xf8); /* mov rax,rdi */
  isa_zero_fill(&ctx,size);byte(&ctx,0xc3);memcpy(code,ctx.code,ctx.n);
  void (*fill)(void*);_Static_assert(sizeof fill==sizeof code,"function pointer size");memcpy(&fill,&code,sizeof fill);
  if(!size) { fill(map);fill(data+page); }
  for(unsigned position=0;position<18;position++) {
   size_t at=position==0?0:position==1?page-size:128+position;
   memset(data,0xa5,page);fill(data+at);
   for(size_t i=0;i<page;i++) if(data[i]!=(i>=at && i<at+size?0:0xa5)) {
    fprintf(stderr,"zero extent size=%u at=%zu byte=%zu\n",size,at,i);return 1;
   }
  }
 }
 munmap(map,page*3);munmap(code,page);return 0;
}
'''


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, timeout=120, **kwargs)


with tempfile.TemporaryDirectory(prefix='dyn-small-zero-') as directory:
    work=Path(directory)
    (work/'emitter.c').write_text(HARNESS)
    run([*shlex.split(os.environ.get('CC','cc')), '-std=c11','-O2','-Wall','-Wextra','-Werror',
         work/'emitter.c','-o',work/'emitter'])
    run([work/'emitter'])
    # C observes the complete physical byte array, including unaligned calls.
    lengths=(1,2,3,7,8,9,15,40,63,64,65,72,127,128,129)
    source=['extern fn oracle() i32',
            'struct Padded { tag:u8, code:i64, memory:rawptr, size:u64, ok:bool }',
            'pub fn zero_padded(p:*Padded) { p.*=Padded{} }']
    c=['#include <stdint.h>', '#include <stddef.h>', 'extern void zero_padded(void*);']
    for size in lengths:
        source += [f'struct B{size} {{ bytes:[{size}]u8 }}',
                   f'pub fn zero_{size}(p:*B{size}) {{ p.*=B{size}{{}} }}']
        c += [f'extern void zero_{size}(void*);']
    source += ['fn main() { if oracle()!=0 { #panic("zero aggregate bytes") } }']
    c += ['int32_t oracle(void) { _Alignas(8) unsigned char b[512];',
          'for(unsigned i=0;i<sizeof b;i++) b[i]=0xa5; zero_padded(b+128);',
          'for(unsigned i=0;i<sizeof b;i++) if(b[i]!=(i>=128 && i<168?0:0xa5)) return 200;']
    for size in lengths:
        c += [f'for(unsigned offset=0;offset<16;offset++) {{',
              'for(unsigned i=0;i<sizeof b;i++) b[i]=0xa5;',
              f'zero_{size}(b+128+offset);',
              f'for(unsigned i=0;i<sizeof b;i++) if(b[i]!=(i>=128+offset && i<128+offset+{size}?0:0xa5)) return {size};', '}']
    c += ['return 0; }']
    project=work/'source';project.mkdir();(project/'main.dyn').write_text('\n'.join(source))
    (work/'oracle.c').write_text('\n'.join(c))
    run([*shlex.split(os.environ.get('CC','cc')), '-std=c11','-O2','-fno-stack-protector','-ffreestanding',
         '-c',work/'oracle.c','-o',work/'oracle.o'])
    for mode in ('tree','ssa'):
        output=work/mode
        run([DYN,'build',project,'--release','--no-cache','--emit-object','--link',work/'oracle.o','--output',output],
            env=dict(os.environ,DYN_NO_SSA='1' if mode=='tree' else '0'))
        run([output])
        if mode=='tree':
            asm=subprocess.check_output(['objdump','-d','-Mintel',str(output)+'.o'],text=True)
            for size in lengths:
                body=re.search(r'<zero_'+str(size)+r'>:\n(.*?)(?=\n\n|\Z)',asm,re.S).group(1)
                if size<=128:
                    assert not re.search(r'\brep\s+stos',body),body
                else:
                    assert re.search(r'\brep\s+stos',body),body
print('PASS small zero fill: guard pages sizes 0..129, unaligned extents, aggregate bytes and bounded shape')
