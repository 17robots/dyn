#!/usr/bin/env python3
"""Result-only cast-chain inlining retains checks, effects and target capture."""
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
ENV=dict(os.environ,DYN_SDK=str(ROOT))
SOURCE=r'''
calls:u64
fn side(x:u64) u64 { calls+=1 defer { calls+=10 } return x }
fn byte(x:u8) u8 { calls+=1 return x }
fn raw(p:*u64) rawptr { calls+=1 return #cast(rawptr,p) }
fn change(target:**u64,replacement:*u64) u64 { calls+=1 target.*=replacement return 7 }
pub fn casted(x:u64) u8 { return #cast(u8,side(x)) }
pub fn chain(x:u64) u16 { return #cast(u16,#cast(u8,side(x))) }
pub fn bits(x:u64) f64 { return #bitcast(f64,side(x)) }
pub fn widen(x:u8) u64 { return byte(x) }
pub fn typed(p:*u64) *u64 { return #cast(*u64,raw(p)) }
fn main() {
 if casted(42)!=42 || calls!=11 { #panic("cast effects") }
 if chain(43)!=43 || calls!=22 { #panic("cast chain") }
 if bits(4608308318706860032)!=1.25 || calls!=33 { #panic("bitcast") }
 if widen(255)!=255 || calls!=34 { #panic("implicit conversion") }
 old:u64=1 other:u64=2 pointer:=&old
 if typed(pointer)!=pointer || calls!=35 { #panic("pointer cast") }
 pointer.*=#cast(u64,change(&pointer,&other))
 if old!=7 || other!=2 || pointer!=&other || calls!=36 { #panic("target capture") }
}
'''
FAILURE=r'''
use "std/io"
calls:u64
fn side(x:u64) u64 { calls+=1 defer { calls+=10 } return x }
enum Choice { A, B }
fn checked(x:u64) Choice { return #cast(Choice,side(x)) }
fn main() {
 defer { _=io.println(io.stdout(),"{}",calls) }
 value:=checked(256)
 calls+=100
 _=value
}
'''
TARGET_FAILURE=r'''
use "std/io"
calls:u64
fn side(x:u64) u64 { calls+=1 return x }
fn main() {
 defer { _=io.println(io.stdout(),"{}",calls) }
 pointer:*u8=nil
 pointer.*=#cast(u8,side(256))
 calls+=100
}
'''


def run(args,**kwargs):
 return subprocess.run([str(x) for x in args],check=True,timeout=120,**kwargs)


with tempfile.TemporaryDirectory(prefix='dyn-inline-casts-') as directory:
 work=Path(directory);project=work/'source';project.mkdir()
 for tree in (False,True):
  env=dict(ENV,DYN_NO_SSA='1' if tree else '0')
  for level in (1,2,3):
   (project/'main.dyn').write_text(SOURCE)
   output=work/f'good-{tree}-{level}'
   run([DYN,'build',project,'--release','--opt-level',level,'--no-cache','--emit-object','--output',output],env=env)
   run([output])
   if not tree and level==3 and platform.machine()=='x86_64' and platform.system()=='Linux':
    asm=subprocess.check_output(['objdump','-dr','-Mintel',str(output)+'.o'],text=True)
    for name,callee in [('casted','side'),('chain','side'),('bits','side'),('widen','byte'),('typed','raw')]:
     body=re.search(r'<'+name+r'>:\n(.*?)(?=\n\n|\Z)',asm,re.S).group(1)
     assert not re.search(r'R_X86_64_\w+\s+'+callee+r'(?:-|\b)',body),body
   if level==1: continue
   for label,source,count,kind in [('cast',FAILURE,'11','checked'),('target',TARGET_FAILURE,'0','main')]:
    (project/'main.dyn').write_text(source)
    output=work/f'{label}-{tree}-{level}'
    run([DYN,'build',project,'--release','--opt-level',level,'--no-cache','--output',output],env=env)
    result=subprocess.run([str(output)],text=True,capture_output=True,timeout=20)
    assert result.returncode!=0,result
    assert result.stdout.splitlines()==[count],result
    assert (' in '+kind+'\n') in result.stderr,result
    if label=='target': assert 'pointer.nonnull.ok' in result.stderr,result
    else: assert 'enum' in result.stderr,result
print('PASS cast-chain inlining: call removal, casts, one-shot effects, defers, target capture and check order/origins')
