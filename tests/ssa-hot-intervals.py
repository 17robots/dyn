#!/usr/bin/env python3
"""Deterministic pressure: hot incoming intervals may displace cold short ones."""
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
static int check(unsigned hot_uses, bool incoming_hot, bool block_registers) {
 static BackendContext ctx;
 Ssa s={0}; SsaAlloc alloc={0}; SsaBlock block={0};
 uint32_t order[]={0}, items[100]; SsaValue values[100];
 memset(values,0,sizeof(values));
 s.ctx=&ctx;s.values=values;s.blocks=&block;s.block_count=1;
 alloc.s=&s;alloc.order=order;alloc.n=1;block.control=-1;
 for(unsigned i=0;i<13;i++) {
  items[i]=i;values[i].op=SO_PARAM;values[i].cls=SC_INT;values[i].hint=-1;
  values[i].a=values[i].b=values[i].c=-1;
  values[i].start=2*i;values[i].end=100+i;
 }
 unsigned hot=incoming_hot?12:0;
 values[hot].end=500;
 unsigned n=13;
 /* Located definitions fill all twelve SysV registers. Pure unlocated
    consumers supply weights without changing register pressure. */
 for(unsigned i=0;i<13;i++) {
  items[n]=n;values[n].op=SO_EXT;values[n].a=i;
  values[n].b=values[n].c=-1;n++;
 }
 for(unsigned i=1;i<hot_uses;i++) {
  items[n]=n;values[n].op=SO_EXT;values[n].a=hot;
  values[n].b=values[n].c=-1;n++;
 }
 block.values.items=items;block.values.count=n;s.value_count=n;
 SsaClobber clobber={.position=50,.mask=UINT64_MAX};
 if(block_registers) { alloc.clobbers=&clobber;alloc.clobber_count=1; }
 if(!ssa_allocate(&alloc))return 1;
 int result=0;
 if(block_registers) { if(values[hot].reg>=0) result=2; }
 else if(hot_uses>4) { if(values[hot].reg<0 || values[hot].slot>=0)result=3; }
 else if(incoming_hot) { if(values[12].reg>=0)result=4; }
 free(alloc.block_start);free(alloc.block_end);
 return result;
}
int main(void) {
 /* Strict >4x, not >=4x. Existing hot interval protection stays intact. */
 if(check(5,true,false))return 10;
 if(check(4,true,false))return 11;
 if(check(1,true,false))return 12;
 if(check(32,false,false))return 13;
 if(check(32,true,true))return 14;
 return 0;
}
'''

def main():
    cc = shlex.split(os.environ.get('CC', 'cc'))
    if platform.system() != 'Linux' or not cc or not shutil.which(cc[0]):
        print('SKIP SSA hot intervals: requires Linux and C compiler')
        return
    with tempfile.TemporaryDirectory(prefix='dyn-hot-intervals-') as directory:
        work = Path(directory)
        (work/'allocator.c').write_text(HARNESS)
        subprocess.run([*cc, '-std=c11', '-D_POSIX_C_SOURCE=200809L', '-O1',
                        '-ffunction-sections', '-fdata-sections', '-I'+str(ROOT/'src'),
                        str(work/'allocator.c'), '-Wl,--gc-sections', '-pthread', '-lm',
                        '-o', str(work/'allocator')], check=True, timeout=120)
        subprocess.run([str(work/'allocator')], check=True, timeout=10)
    print('PASS SSA hot intervals: incoming/existing weights, strict threshold, clobbers')

if __name__ == '__main__':
    main()
