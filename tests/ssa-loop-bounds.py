#!/usr/bin/env python3
"""Exact dominating unsigned bounds remove checks; unrelated paths retain them."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
FUNCTIONS = '''use "std/io"
pub fn loop_sum(s:[]const u8) u64 {
  sum:u64=0
  for i in 0..#len(s) { sum=#wrap(sum+#cast(u64,s[i])) }
  return sum
}
pub fn reversed(s:[]const u8,i:usize) u8 {
  if #len(s)>i { return s[i] }
  return 0
}
pub fn false_edge(s:[]const u8,i:usize) u8 {
  if i>=#len(s) { return 0 }
  return s[i]
}
pub fn joined(s:[]const u8,i:usize,choose:bool) u8 {
  if choose { if i>=#len(s) { return 0 } }
  return s[i]
}
pub fn equality(s:[]const u8,i:usize) u8 {
  if i<=#len(s) { return s[i] }
  return 0
}
pub fn signed(s:[]const u8,i:isize) u8 {
  if i<#cast(isize,#len(s)) { return s[i] }
  return 0
}
pub fn changed(s:[]const u8,i:usize) u8 {
  if i<#len(s) { return s[#wrap(i+1)] }
  return 0
}
pub fn phi(s:[]const u8,i:usize,choose:bool) u8 {
  if i<#len(s) {
    at:=i
    if choose { at=#len(s) }
    return s[at]
  }
  return 0
}
'''
CASES = [
 ('success', '''s:="abc"
 if loop_sum(s)!=294 || loop_sum("")!=0 || reversed(s,1)!=98 || reversed(s,3)!=0 || false_edge(s,2)!=99 || false_edge(s,3)!=0 || joined(s,2,true)!=99 || signed(s,1)!=98 || phi(s,1,false)!=98 || equality(s,1)!=98 || changed(s,0)!=98 { #panic("value") }''', False),
 ('join', '_=joined("abc",3,false)', True),
 ('equality', '_=equality("abc",3)', True),
 ('signed-negative', '_=signed("abc",-1)', True),
 ('changed-index', '_=changed("abc",2)', True),
 ('changed-phi', '_=phi("abc",1,true)', True),
]

def main():
 with tempfile.TemporaryDirectory(prefix='dyn-loop-bounds-') as directory:
  work=Path(directory)
  for mode in ('ssa','tree'):
   env=dict(os.environ,DYN_SDK=str(ROOT))
   env.pop('DYN_NO_SSA',None)
   if mode=='tree': env['DYN_NO_SSA']='1'
   for name,body,panic in CASES:
    (work/'main.dyn').write_text(FUNCTIONS+'\nfn main() {\n'+body+'\n_=io.write_all(io.stdout(),"OK\\n")\n}\n')
    binary=work/'program'
    build=subprocess.run([DYN,'build',str(work),'--release','--opt-level','3','--no-cache','--quiet','--opt-remarks','--output',str(binary)],env=env,text=True,capture_output=True,timeout=120)
    assert build.returncode==0,(mode,name,build.stderr)
    if mode=='ssa' and name=='success':
     for function in ('loop_sum','reversed','false_edge','joined','equality','signed','changed','phi'):
      assert re.search(r'remark: '+function+r': SSA code generation,',build.stderr),build.stderr
    elif mode=='tree': assert 'SSA code generation' not in build.stderr,build.stderr
    result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
    if panic: assert result.returncode!=0 and 'index.ok' in result.stderr.lower() and result.stdout=='',(mode,name,result)
    else:
     assert result.returncode==0 and result.stdout=='OK\n',(mode,name,result)
     if mode=='ssa':
      dis=subprocess.run(['objdump','-d','-Mintel',str(binary)],capture_output=True,text=True,check=True,timeout=15).stdout
      functions=re.split(r'\n(?=[0-9a-f]+ <)',dis)
      for function in ('loop_sum','reversed','false_edge'):
       pieces=[f for f in functions if re.match(r'[0-9a-f]+ <(?:[^>]*_)?'+function+r'>:',f)]
       assert len(pieces)==1,(function,'missing symbol')
       assert 'dyn_check_failed' not in pieces[0],pieces[0]
   print(f'PASS exact loop bounds {mode}: {len(CASES)} cases',flush=True)

if __name__=='__main__': main()
