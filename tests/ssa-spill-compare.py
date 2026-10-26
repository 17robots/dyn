#!/usr/bin/env python3
"""Deterministic x86 spill comparisons: folded bytes and executable flags."""
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include "backend/compiler.c"
#include <sys/mman.h>
#define abort() do { fprintf(stderr,"spill comparison failed at line %d\n",__LINE__); __builtin_abort(); } while(0)

static int truth(Cond c, uint64_t a, uint64_t b) {
 switch(c) {
 case CC_E:return a==b; case CC_NE:return a!=b;
 case CC_L:return (int64_t)a<(int64_t)b; case CC_LE:return (int64_t)a<=(int64_t)b;
 case CC_G:return (int64_t)a>(int64_t)b; case CC_GE:return (int64_t)a>=(int64_t)b;
 case CC_B:return a<b; case CC_BE:return a<=b; case CC_A:return a>b; case CC_AE:return a>=b;
 default:abort();
 }
}
static void check(unsigned mode, unsigned reg, int64_t immediate, Cond condition) {
 static BackendContext storage;
 BackendContext *ctx=&storage; SsaValue values[2]={0}; Ssa s={0}; SsaEmit e={0};
 s.ctx=ctx;s.values=values;s.value_count=2;e.s=&s;e.ctx=ctx;e.spill_base=-8;
 for(unsigned i=0;i<2;i++) { values[i].op=SO_PARAM;values[i].cls=SC_INT;values[i].reg=-1;values[i].slot=(int32_t)i; }
 /* SysV inputs a,b arrive in RDI,RSI. The test fixes locations directly, so
    allocator heuristics cannot accidentally stop exercising the spill path. */
 CODE(0x55,0x48,0x89,0xe5,0x48,0x83,0xec,0x20);
 x86_mem_op(ctx,-1,true,OP1(0x89),X_RDI,(SsaMemory){X_RBP,-1,1,-8},false);
 x86_mem_op(ctx,-1,true,OP1(0x89),X_RSI,(SsaMemory){X_RBP,-1,1,-16},false);
 if(mode==0) { values[1].reg=(int16_t)reg;values[1].slot=-1;x86_mov(ctx,reg,X_RSI); }
 if(mode==1 || mode==4) { values[1].op=SO_CONST;values[1].slot=-1;values[1].aux=immediate; }
 if(mode==3) { values[0].op=SO_CONST;values[0].slot=-1;values[0].aux=immediate; }
 size_t start=ctx->text.n;
 Cond actual=ssa_compare_values(&e,0,1,condition);
 /* Folded forms begin directly with CMP, not a scratch reload. */
 if(mode==0) {
   unsigned opcode=ctx->text.data[start+1];
   if(opcode!=0x39 || ctx->text.n-start!=4u) abort();
 }
 if((mode==1||mode==3) && ctx->text.data[start+1]!=0x8b)abort();
 ssa_setcc(ctx,X_RAX,actual);
 CODE(0x0f,0xb6,0xc0,0xc9,0xc3);
 if(ctx->text.failed)abort();
 void *memory=mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
 if(memory==MAP_FAILED)abort();
 memcpy(memory,ctx->text.data,ctx->text.n);
 if(mprotect(memory,4096,PROT_READ|PROT_EXEC))abort();
 int (*fn)(uint64_t,uint64_t);memcpy(&fn,&memory,sizeof(fn));
 const uint64_t inputs[]={0,1,127,128,255,256,UINT64_C(0x7fffffff),UINT64_C(0x80000000),
   UINT64_C(0x7fffffffffffffff),UINT64_C(0x8000000000000000),UINT64_MAX-1,UINT64_MAX};
 for(unsigned i=0;i<sizeof(inputs)/sizeof(*inputs);i++)for(unsigned j=0;j<sizeof(inputs)/sizeof(*inputs);j++) {
   uint64_t a=inputs[i],b=inputs[j];
   if(mode==1 || mode==4)b=(uint64_t)immediate;
   if(mode==3)a=(uint64_t)immediate;
   if(fn(inputs[i],inputs[j])!=truth(condition,a,b))abort();
 }
 munmap(memory,4096);free(ctx->text.data);ctx->text=(Bytes){0};
}
int main(void) {
 const Cond conditions[]={CC_E,CC_NE,CC_L,CC_LE,CC_G,CC_GE,CC_B,CC_BE,CC_A,CC_AE};
 const int64_t immediates[]={INT32_MIN,-129,-128,-1,0,1,127,128,INT32_MAX};
 for(unsigned c=0;c<sizeof(conditions)/sizeof(*conditions);c++) {
   const unsigned regs[]={X_RCX,X_R8,X_R10,X_R11};
   for(unsigned r=0;r<sizeof(regs)/sizeof(*regs);r++)check(0,regs[r],0,conditions[c]);
   check(2,0,0,conditions[c]); /* Two spills must keep their safe fallback. */
   for(unsigned i=0;i<sizeof(immediates)/sizeof(*immediates);i++) {
     check(1,0,immediates[i],conditions[c]);check(3,0,immediates[i],conditions[c]);
   }
   check(4,0,INT64_C(0x1234567887654321),conditions[c]);
 }
 return 0;
}
'''


def main():
    cc = shlex.split(os.environ.get('CC', 'cc'))
    if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        print('SKIP SSA spill compare: executable harness requires Linux x86-64')
        return
    if not cc or not shutil.which(cc[0]):
        print('SKIP SSA spill compare: C compiler unavailable')
        return
    with tempfile.TemporaryDirectory(prefix='dyn-spill-compare-') as directory:
        work = Path(directory)
        (work/'compare.c').write_text(HARNESS)
        subprocess.run([*cc, '-std=c11', '-D_GNU_SOURCE', '-D_POSIX_C_SOURCE=200809L', '-O1',
                        '-ffunction-sections', '-fdata-sections', '-I'+str(ROOT/'src'),
                        str(work/'compare.c'), '-Wl,--gc-sections', '-pthread', '-lm',
                        '-o', str(work/'compare')], check=True, timeout=120)
        subprocess.run([str(work/'compare')], check=True, timeout=20)
    print('PASS SSA spill compare: 240 forms, 34560 executable flag checks')


if __name__ == '__main__':
    main()
