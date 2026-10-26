#!/usr/bin/env python3
"""Prove exact masked extension folding without changing truncation/sign semantics."""
from pathlib import Path
import os, platform, re, shutil, subprocess, tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve()
if platform.system()!='Linux' or platform.machine() not in ('x86_64','amd64') or not shutil.which('cc') or not shutil.which('objdump'):
    print('SKIP masked extension: Linux x86-64 C/objdump fixture');raise SystemExit(0)
def run(args,**kw):
    p=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=120,**kw)
    assert p.returncode==0,(args,p.stdout,p.stderr)
    return p
source=[]; declarations=[];checks=[];positive=[];negative=[];full=[]
for width in (8,16,32):
 for signed in (False,True):
  ret='i64' if signed else 'u64';ctype='int64_t' if signed else 'uint64_t';narrow=('i' if signed else 'u')+str(width)
  bound=(1<<(width-int(signed)))-1
  for reverse in (False,True):
   for case,(safe,mask) in enumerate(((True,bound),(False,(1<<width) if not signed else (1<<width)-1),(False,(1<<64)-1),(False,(1<<64)-2))):
    name=f'f_{width}_{int(signed)}_{int(reverse)}_{case}';expr=f'{mask}&x' if reverse else f'x&{mask}'
    source.append(f'pub fn {name}(x:u64) {ret} {{ return #cast({ret},#cast({narrow},{expr})) }}')
    declarations.append(f'extern {ctype} {name}(uint64_t);')
    expected=f'({ctype})({narrow.replace("i","int").replace("u","uint")}_t)(x&UINT64_C({mask}))'
    checks.append(f'if({name}(x)!={expected})return {len(checks)+1};')
    (positive if safe else negative).append(name)
    source.append(f'pub fn {name}_ref(x:u64) {ret} {{ return #cast({ret},{expr}) }}')
# Source-level identity64 controls do not establish SO_EXT64 branch coverage:
# the builder may omit full-width normalization before this optimization runs.
for signed in (False,True):
 ret='i64' if signed else 'u64';ctype='int64_t' if signed else 'uint64_t'
 for reverse in (False,True):
  name=f'full_{int(signed)}_{int(reverse)}';expr='18446744073709551615&x' if reverse else 'x&18446744073709551615'
  source.append(f'pub fn {name}(x:u64) {ret} {{ return #cast({ret},{expr}) }}')
  source.append(f'pub fn {name}_ref(x:u64) {ret} {{ return #cast({ret},x) }}')
  declarations.append(f'extern {ctype} {name}(uint64_t);')
  checks.append(f'if({name}(x)!=({ctype})x)return {len(checks)+1};')
  full.append(name)
c='''#include <stdint.h>
#include <stddef.h>
'''+ '\n'.join(declarations)+'''
int main(void){uint64_t values[]={0,1,63,127,128,255,256,32767,32768,65535,65536,2147483647,2147483648ULL,4294967295ULL,4294967296ULL,UINT64_MAX};
for(size_t i=0;i<sizeof(values)/sizeof(values[0])+10000;i++){uint64_t x=i<16?values[i]:i*UINT64_C(11400714819323198485);
'''+ '\n'.join(checks)+'\n}return 0;}\n'
with tempfile.TemporaryDirectory(prefix='dyn-masked-extension-') as t:
 w=Path(t);project=w/'project';project.mkdir();(project/'main.dyn').write_text('\n'.join(source)+'\n');(w/'oracle.c').write_text(c)
 for tree in (False,True):
  env=dict(os.environ,DYN_SDK=str(ROOT));env.pop('DYN_NO_SSA',None)
  if tree:env['DYN_NO_SSA']='1'
  out=w/('tree' if tree else 'ssa')
  p=run([DYN,'build',project,'--shared','--release','--opt-level','3','--cpu','generic','--no-cache','--quiet','--opt-remarks','--no-link','--emit-object','--output',out],env=env)
  obj=Path(str(out)+'.o')
  run(['cc','-O2',w/'oracle.c',obj,ROOT/'build/dynrt_shared.o',ROOT/'build/dynrt_support.o','-o',w/'test'])
  run([w/'test'])
  if not tree:
   assert all(f'{name}: SSA code generation' in p.stderr for name in positive+negative+full),p.stderr
   def body(name):
    text=run(['objdump','-d','-Mintel','--disassemble='+name,obj]).stdout
    return [line.split('\t')[-1].strip() for line in text.splitlines() if re.match(r'^\s*[0-9a-f]+:',line)]
   for name in positive:
    assert body(name)==body(name+'_ref'),(name,body(name),body(name+'_ref'))
   for name in full:
    # Constant-left AND may survive a separate canonicalization limit. Both
    # instruction forms must still be identity64 with no narrowing operation.
    instructions=[x for x in body(name) if not re.match(r'and\s+\w+,0xffffffffffffffff$',x)]
    assert instructions==body(name+'_ref'),(name,body(name),body(name+'_ref'))
   for name in negative:
    b=body(name)
    assert b!=body(name+'_ref'),(name,b)
    assert any(re.search(r'\b(movzx|movsx|movsxd|and|shl|sar)\b|\bmov\s+(?:e[a-z]{2}|r[0-9]+d),',x) for x in b),(name,b)
 print(f'PASS masked extensions: {len(checks)} cases, {len(checks)*10016} values per SSA/tree; exact positive instruction controls')
