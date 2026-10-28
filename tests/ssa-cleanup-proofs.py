#!/usr/bin/env python3
"""Exact bounds/address facts also prove checks lowered through cleanup edges."""
from pathlib import Path
import os
import platform
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
FUNCTIONS = r'''
use "std/io"
extern fn opaque(value:usize) usize
extern foreign_byte:u8
extern fn foreign_alignment() usize
fn cleanup() { _=io.write_all(io.stdout(),"D") }
pub fn local_plain() u64 {
 value:=#cast(u64,opaque(7))
 pointer:=&value
 pointer.*=#wrap(pointer.*+1)
 return pointer.*
}
pub fn local_deferred() u64 {
 defer cleanup()
 value:=#cast(u64,opaque(7))
 pointer:=&value
 pointer.*=#wrap(pointer.*+1)
 return pointer.*
}
pub fn wrapped_compare() usize {
 defer cleanup()
 value:u64=7
 delta:=opaque(#wrap(0-#cast(usize,&value)))
 view:=(#cast(*u8,&value))[..opaque(~#cast(usize,0))]
 pointer:=&view[delta]
 // Compare the forged address only; never dereference it.
 if pointer==nil { return opaque(11) }
 return opaque(22)
}
pub fn foreign_compare() usize {
 defer cleanup()
 if (#cast(usize,&foreign_byte)&7)==0 { return opaque(11) }
 return opaque(22)
}
pub fn foreign_deref() u64 {
 defer cleanup()
 return (#cast(*u64,&foreign_byte)).*
}
pub fn incoming(pointer:*u64) u64 {
 defer cleanup()
 return pointer.*
}
pub fn loop_sum(s:[]const u8) u64 {
 defer cleanup()
 sum:u64=0
 for i in 0..#len(s) { sum=#wrap(sum+#cast(u64,s[i])) }
 return sum
}
pub fn nested(s:[]const u8) u64 {
 defer cleanup()
 sum:u64=0
 for r in 0..opaque(2) {
  for i in 0..#len(s) { if i==opaque(1) { continue }
  sum=#wrap(sum+#cast(u64,s[i])) }
 }
 return sum
}
pub fn reversed(s:[]const u8,i:usize) u8 {
 defer cleanup()
 if #len(s)>i { return s[i] }
 return 0
}
pub fn false_edge(s:[]const u8,i:usize) u8 {
 defer cleanup()
 if i>=#len(s) { return 0 }
 return s[i]
}
pub fn contradiction(s:[]const u8,i:usize) u8 {
 defer cleanup()
 if i<#len(s) { if i>=#len(s) { #panic("unreachable") }
 return s[i] }
 return 0
}
pub fn swapped(s:[]const u8,i:usize) u8 {
 defer cleanup()
 if #len(s)>i { if #len(s)<=i { #panic("unreachable") }
 return s[i] }
 return 0
}
pub fn joined(s:[]const u8,i:usize,choose:bool) u8 {
 defer cleanup()
 if choose { if i>=#len(s) { return 0 } }
 return s[i]
}
pub fn equality(s:[]const u8,i:usize) u8 {
 defer cleanup()
 if i<=#len(s) { return s[i] }
 return 0
}
pub fn signed(s:[]const u8,i:isize) u8 {
 defer cleanup()
 if i<#cast(isize,#len(s)) { return s[i] }
 return 0
}
pub fn changed(s:[]const u8,i:usize) u8 {
 defer cleanup()
 if i<#len(s) { return s[#wrap(i+1)] }
 return 0
}
pub fn phi(s:[]const u8,i:usize,choose:bool) u8 {
 defer cleanup()
 if i<#len(s) { at:=i
 if choose { at=#len(s) }
 return s[at] }
 return 0
}
'''
CASES = [
 ('success', '''s:="abc"
 if loop_sum(s)!=294 || loop_sum("")!=0 || nested(s)!=392 || reversed(s,opaque(1))!=98 || reversed(s,opaque(3))!=0 || false_edge(s,opaque(2))!=99 || false_edge(s,opaque(3))!=0 || contradiction(s,opaque(1))!=98 || swapped(s,opaque(1))!=98 || reversed(s,opaque(18446744073709551615))!=0 || joined(s,opaque(2),true)!=99 || equality(s,opaque(1))!=98 || signed(s,#cast(isize,opaque(1)))!=98 || changed(s,opaque(0))!=98 || phi(s,opaque(1),false)!=98 { #panic("value") }''', False, 15),
 ('joined', '_=joined("abc",opaque(3),false)', True, 1),
 ('equality', '_=equality("abc",opaque(3))', True, 1),
 ('signed', '_=signed("abc",-#cast(isize,opaque(1)))', True, 1),
 ('changed', '_=changed("abc",opaque(2))', True, 1),
 ('phi', '_=phi("abc",opaque(1),true)', True, 1),
 ('local', 'value:u64=9\nif local_plain()!=8 || local_deferred()!=8 || incoming(&value)!=9 { #panic("value") }', False, 2),
 ('wrapped', 'if wrapped_compare()!=11 { #panic("wrapped address comparison") }', False, 1),
 ('foreign', 'if foreign_alignment()!=1 || foreign_compare()!=22 { #panic("foreign alignment") }', False, 1),
 ('foreign_guard', '_=foreign_deref()', True, 1),
 ('null', '_=incoming(#cast(*u64,opaque(0)))', True, 1),
 ('misaligned', '_=incoming(#cast(*u64,opaque(1)))', True, 1),
]


def run(args, **kwargs):
 return subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=120,**kwargs)


def main():
 if platform.system()!='Linux' or platform.machine() not in ('x86_64','amd64') or not shutil.which('cc') or not shutil.which('objdump'):
  print('SKIP cleanup proofs: Linux x64, cc and objdump required')
  return
 with tempfile.TemporaryDirectory(prefix='dyn-cleanup-proofs-') as directory:
  work=Path(directory)
  (work/'opaque.c').write_text(r'''#include <stddef.h>
#include <stdint.h>
__attribute__((noinline)) size_t opaque(size_t x) { __asm__ volatile("" : "+r"(x)); return x; }
/* An independently placed extern byte at precisely 1 modulo 8. */
__asm__(".pushsection .data\n.balign 8\n.byte 0\n.globl foreign_byte\n.type foreign_byte,@object\nforeign_byte: .byte 7\n.size foreign_byte,1\n.popsection\n");
extern unsigned char foreign_byte;
size_t foreign_alignment(void) { return (uintptr_t)&foreign_byte & 7; }
''')
  compiled=run(['cc','-c',work/'opaque.c','-o',work/'opaque.o'])
  assert compiled.returncode==0,compiled.stderr
  observations={}
  for mode in ('ssa','tree'):
   env=dict(os.environ,DYN_SDK=str(ROOT))
   env.pop('DYN_NO_SSA',None)
   if mode=='tree':env['DYN_NO_SSA']='1'
   for name,body,panic,cleanups in CASES:
    source=work/'source';source.mkdir(exist_ok=True)
    (source/'main.dyn').write_text(FUNCTIONS+'\nfn main() {\n'+body+'\n_=io.write_all(io.stdout(),"OK\\n")\n}\n')
    binary=work/'program'
    built=run([DYN,'build',source,'--release','--opt-level','3','--no-cache','--quiet','--opt-remarks','--link',work/'opaque.o','--output',binary],env=env)
    assert built.returncode==0,(mode,name,built.stderr)
    if mode=='ssa' and name in ('success','local'):
     functions=('local_plain','local_deferred','incoming') if name=='local' else ('loop_sum','nested','reversed','false_edge','contradiction','swapped','joined','equality','signed','changed','phi')
     for function in functions:
      assert re.search(r'remark: '+function+r': SSA code generation,',built.stderr),(function,built.stderr)
    if mode=='ssa' and name in ('wrapped','foreign','foreign_guard'):
     function={'wrapped':'wrapped_compare','foreign':'foreign_compare','foreign_guard':'foreign_deref'}[name]
     assert re.search(r'remark: '+function+r': SSA code generation,',built.stderr),built.stderr
    if mode=='tree':assert 'SSA code generation' not in built.stderr,built.stderr
    result=run([binary])
    assert result.stdout=='D'*cleanups+('' if panic else 'OK\n'),(mode,name,result)
    assert (result.returncode!=0)==panic,(mode,name,result)
    if panic:
     diagnostic={'null':'pointer.nonnull.ok','misaligned':'pointer.aligned.ok','foreign_guard':'pointer.aligned.ok'}.get(name,'index.ok')
     assert diagnostic in result.stderr.lower(),(mode,name,result)
    observations[mode,name]=(result.returncode,result.stdout,result.stderr)
    if mode=='ssa' and name in ('success','local'):
     dis=run(['objdump','-d','-Mintel',binary])
     assert dis.returncode==0,dis.stderr
     pieces=re.split(r'\n(?=[0-9a-f]+ <)',dis.stdout)
     functions=('local_plain','local_deferred','incoming') if name=='local' else ('loop_sum','nested','reversed','false_edge','contradiction','swapped')
     for function in functions:
      found=[p for p in pieces if re.match(r'[0-9a-f]+ <(?:[^>]*_)?'+function+r'>:',p)]
      assert len(found)==1,(function,'missing symbol')
      if function=='incoming':
       assert 'dyn_check_failed' in found[0],(function,'incoming pointer checks disappeared',found[0])
      else:assert 'dyn_check_failed' not in found[0],(function,found[0])
   print(f'PASS cleanup proofs {mode}: {len(CASES)} exact cleanup/value cases',flush=True)
  for name,*_ in CASES:assert observations['ssa',name]==observations['tree',name],name
  # Both constructed and live SSA32 preflights inspect the rewritten graph.
  # These are compile checks; guest execution remains in bare-ssa-cleanup.py.
  (source/'main.dyn').write_text(FUNCTIONS+'\nfn main() {\n'+CASES[0][1].replace('opaque(18446744073709551615)','opaque(3)')+'\n}\n')
  env=dict(os.environ,DYN_SDK=str(ROOT));env.pop('DYN_NO_SSA',None)
  for target in ('riscv32-none','riscv32-none-soft','thumbv7em-none','thumbv7em-none-soft'):
   built=run([DYN,'build',source,'--target',target,'--release','--opt-level','3','--no-cache','--quiet','--opt-remarks','--emit-object','--no-link','--output',work/'cross.o'],env=env)
   assert built.returncode==0,(target,built.stderr)
   for function in ('loop_sum','nested','reversed','false_edge','contradiction','swapped','joined','equality','signed','changed','phi'):
    assert re.search(r'remark: '+function+r': SSA code generation,',built.stderr),(target,function,built.stderr)
  print('PASS cleanup proofs: all four paired targets pass constructed/live SSA preflight',flush=True)


if __name__=='__main__':main()
