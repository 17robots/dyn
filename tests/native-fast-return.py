#!/usr/bin/env python3
"""Recursive base cases return before frame setup without skipping effects."""
import os
from pathlib import Path
import platform
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
if platform.system() != 'Linux' or platform.machine() != 'x86_64':
    print('SKIP recursive frame bypass: requires x86-64 Linux')
    raise SystemExit(0)
SOURCE = '''use "std/io"
count:u64=0
pub fn less(n:u64) u64 { if n<2 { return n }
return less(n-1)+less(n-2) }
pub fn alternate(n:u64) u64 { if n<=1 { return n }
return alternate(n-2)+alternate(n-2) }
pub fn equal(n:u64,base:u64) u64 { if n==0 { return base }
return equal(n-1,base)+equal(n-1,base) }
pub fn different(n:u64) u64 { if n!=0 { return n }
return different(1) }
pub fn above(n:u64) u64 { if n>200 { return n }
return above(n+1) }
pub fn at_least(n:u64) u64 { if n>=127 { return n }
return at_least(n+1) }
pub fn at_most(a:u64,b:u64,c:u64,d:u64,e:u64,n:u64) u64 {
  if n<=1 { return a }
  return at_most(a,b,c,d,e,n-1)+at_most(a,b,c,d,e,n-1)
}
pub fn later(n:u64) u64 { if n<2 { return n }
count+=1
return later(n-1)+later(n-2) }
pub fn unsafe(n:u64) u64 { if n<1 { return n }
return unsafe(n-2)+unsafe(n-1) }
pub fn overflowing(n:u64) u64 { if n<2 { return n }
return overflowing(n-1)*18446744073709551615+overflowing(n-2) }
pub fn signed(n:i64) i64 { if n<2 { return n }
return signed(n-1)+signed(n-2) }
pub fn effect(n:u64) u64 { count+=1
if n<2 { return n }
return effect(n-1)+effect(n-2) }
pub fn cleanup(n:u64) u64 { defer { count+=1 }
if n<2 { return n }
return cleanup(n-1)+cleanup(n-2) }
fn main() {
  _=io.println(io.stdout(),"{} {} {} {} {} {} {} {} {} {} {}",less(0),less(1),less(15),
    equal(0,7),equal(6,7),different(0),above(199),above(18446744073709551615),
    at_least(125),at_most(3,4,5,6,7,5),signed(15))
  _=io.println(io.stdout(),"{} {} {} {} {}",less(2),less(3),less(7),less(8),alternate(9))
  _=later(7)
  _=effect(7)
  _=cleanup(7)
  _=io.println(io.stdout(),"{}",count)
}
'''

def symbols(path):
    data=path.read_bytes()
    table=struct.unpack_from('<Q',data,40)[0]
    stride,count=struct.unpack_from('<HH',data,58)
    sections=[struct.unpack_from('<IIQQQQIIQQ',data,table+i*stride) for i in range(count)]
    found={}
    for section in sections:
        if section[1]!=2: continue
        strings=sections[section[6]]
        names=data[strings[4]:strings[4]+strings[5]]
        for at in range(section[4],section[4]+section[5],section[9]):
            name,info,_,index,value,size=struct.unpack_from('<IBBHQQ',data,at)
            if info&15!=2 or not index: continue
            label=names[name:].split(b'\0',1)[0].decode()
            code=sections[index][4]+value
            found[label]=data[code:code+size]
    return found

with tempfile.TemporaryDirectory(prefix='dyn-base-return-') as directory:
    work=Path(directory)
    (work/'main.dyn').write_text(SOURCE)
    results=[]
    for mode in ('ssa','tree'):
        output=work/mode
        env=dict(os.environ,DYN_NO_SSA='1' if mode=='tree' else '0')
        build=subprocess.run([DYN,'build',str(work),'--release','--no-cache','--emit-object','--output',str(output)],
                             env=env,text=True,capture_output=True,timeout=120)
        assert build.returncode==0,build.stderr
        result=subprocess.run([str(output)],text=True,capture_output=True,timeout=20)
        assert result.returncode==0,result.stderr
        results.append(result.stdout)
        if mode=='ssa':
            code=symbols(Path(str(output)+'.o'))
            for name in ('less','equal','different','above','at_least','at_most'):
                assert code[name][0] in (0x48,0x49) and 0xc3 in code[name][:40],(name,code[name][:16].hex())
            assert code['less'][3]==8 and code['alternate'][3]==8, code['less'][:8].hex()
            assert code['unsafe'][3]==1 and code['overflowing'][3]==2
            assert code['later'][3]==2, code['later'][:8].hex()
            for name in ('signed','effect','cleanup'):
                assert code[name][0]==0x55,(name,code[name][:16].hex())
    assert results[0]==results[1],results
    for call in ('unsafe(1)', 'overflowing(3)'):
        (work/'main.dyn').write_text(SOURCE[:SOURCE.index('fn main()')]+'fn main() { _='+call+' }\n')
        failures=[]
        for mode in ('ssa','tree'):
            output=work/('panic-'+mode)
            env=dict(os.environ,DYN_NO_SSA='1' if mode=='tree' else '0')
            subprocess.run([DYN,'build',str(work),'--release','--no-cache','--quiet','--output',str(output)],env=env,check=True,timeout=120)
            result=subprocess.run([str(output)],text=True,capture_output=True,timeout=20)
            assert result.returncode!=0 and 'overflow.ok' in result.stderr,(call,mode,result)
            failures.append(result.returncode)
        assert failures[0]==failures[1],failures
print('PASS recursive base cases: all unsigned comparisons, sixth argument, limits, effects, signed and defer exclusions')
