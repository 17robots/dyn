#!/usr/bin/env python3
"""Repeated expensive loop constants use registers; pressure rematerializes them."""
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
LIMIT = 1844674407370955161
INPUTS = ('', '0', '9', '1844674407370955160', '1844674407370955161',
          '1844674407370955165', '18446744073709551615',
          '18446744073709551616', '999999999999999999999999999')
SOURCE = '''use "std/io"
pub fn guarded(s:[]const u8) u64 {
  value:u64=0
  for digit in s {
    d:=#cast(u64,digit-48)
    if value>1844674407370955161 { return 18446744073709551615 }
    if value==1844674407370955161 && d>5 { return 18446744073709551615 }
    value=#wrap(value*10+d)
  }
  return value
}
callback:fn([]const u8) u64=guarded
fn main() {
CHECKS
  _=io.write_all(io.stdout(),"CONSTANT PASS\\n")
}
'''

# This constructs intervals directly so the fallback test deterministically
# exercises eviction, rather than depending on a source program's allocation.
HARNESS = r'''
#include "backend/compiler.c"
int main(void) {
 static BackendContext ctx; Ssa s={0}; SsaAlloc alloc={0};
 uint32_t order[]={0}; SsaBlock block={0}; uint32_t items[40]; SsaValue values[40];
 memset(values,0,sizeof(values));
 s.ctx=&ctx; s.values=values; s.value_count=40; s.blocks=&block; s.block_count=1;
 block.values.items=items; block.values.count=40; block.control=-1;
 alloc.s=&s; alloc.order=order; alloc.n=1;
 for(unsigned i=0;i<40;i++) {
  items[i]=i; values[i].cls=SC_INT; values[i].hint=-1;
  values[i].a=values[i].b=values[i].c=-1;
  values[i].start=2*i; values[i].end=1000-i;
  values[i].op=i?SO_ADD:SO_CONST;
 }
 values[0].retain_constant=true; values[0].aux=INT64_C(1844674407370955161);
 if(!ssa_allocate(&alloc)) return 1;
 if(values[0].reg>=0 || values[0].slot>=0 || values[0].retain_constant || ssa_located(&values[0])) return 2;
 /* No free register and no useful eviction: reject the constant outright. */
 for(unsigned i=0;i<40;i++) {
  values[i].start=2*i; values[i].end=1000+i;
  values[i].op=i==39?SO_CONST:SO_ADD; values[i].retain_constant=i==39;
 }
 alloc.spill_slots=0;
 if(!ssa_allocate(&alloc)) return 3;
 if(values[39].reg>=0 || values[39].slot>=0 || values[39].retain_constant || ssa_located(&values[39])) return 4;
 /* A repeatedly used long-lived parameter must survive cold temporaries. */
 for(unsigned i=0;i<40;i++) {
  values[i].start=2*i; values[i].end=1000-i;
  values[i].op=i?SO_ADD:SO_PARAM; values[i].retain_constant=false;
  values[i].a=i?0:-1; values[i].b=values[i].c=-1;
 }
 alloc.spill_slots=0;
 if(!ssa_allocate(&alloc)) return 5;
 if(values[0].reg<0 || values[0].slot>=0) return 6;
 return 0;
}
'''


def main():
    if platform.machine().lower() not in ('x86_64', 'amd64') or not shutil.which('objdump'):
        print('SKIP loop constants: requires x86-64 and objdump')
        return
    with tempfile.TemporaryDirectory(prefix='dyn-loop-constants-') as directory:
        work = Path(directory)
        checks = []
        for text in INPUTS:
            expected = min(int(text or '0'), (1 << 64)-1)
            checks.append(f'if callback("{text}")!={expected} {{ #panic("constant boundary") }}')
        (work/'main.dyn').write_text(SOURCE.replace('CHECKS', '\n'.join(checks)))
        for mode in ('ssa', 'tree'):
            env = dict(os.environ, DYN_SDK=str(ROOT))
            env.pop('DYN_NO_SSA', None)
            if mode == 'tree':
                env['DYN_NO_SSA'] = '1'
            binary = work/mode
            build = subprocess.run([DYN, 'build', str(work), '--release', '--opt-level', '3',
                                    '--no-cache', '--quiet', '--opt-remarks', '--output', str(binary)],
                                   env=env, text=True, capture_output=True, timeout=120)
            assert build.returncode == 0, build.stderr
            result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=10)
            assert result.returncode == 0 and result.stdout == 'CONSTANT PASS\n', result
            if mode == 'ssa':
                assert re.search(r'remark: guarded: SSA code generation,', build.stderr), build.stderr
                asm = subprocess.check_output(['objdump', '-d', '-Mintel', str(binary)], text=True, timeout=20)
                body = re.search(r'<(?:[^>]*_)?guarded>:\n(.*?)(?=\n\n|\Z)', asm, re.S)
                assert body, 'guarded symbol missing'
                loads = re.findall(r'movabs\s+\w+,0x1999999999999999\b', body[1])
                assert len(loads) == 1, body[1]
            else:
                assert 'SSA code generation' not in build.stderr, build.stderr
            print(f'PASS loop constants {mode}: {len(INPUTS)} overflow boundaries', flush=True)

        cc = shlex.split(os.environ.get('CC', 'cc'))
        if not cc or not shutil.which(cc[0]) or platform.system() != 'Linux':
            print('SKIP deterministic constant eviction: requires Linux and CC')
            return
        (work/'allocator.c').write_text(HARNESS)
        subprocess.run([*cc, '-std=c11', '-D_POSIX_C_SOURCE=200809L', '-O1',
                        '-ffunction-sections', '-fdata-sections', '-I'+str(ROOT/'src'),
                        str(work/'allocator.c'), '-Wl,--gc-sections', '-pthread', '-lm',
                        '-o', str(work/'allocator')], check=True, timeout=120)
        subprocess.run([str(work/'allocator')], check=True, timeout=10)
        print('PASS deterministic constant eviction and rejected-allocation rematerialization', flush=True)


if __name__ == '__main__':
    main()
