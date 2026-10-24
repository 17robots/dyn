#!/usr/bin/env python3
"""Integer branches reuse flags without changing range or short-circuit effects."""
import ctypes
import os
from pathlib import Path
import platform
import random
import shutil
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
SOURCE = '''pub fn outside8(x:u8) bool { return x<48 || x>57 }
pub fn inside8(x:u8) bool { return x>=48 && x<=57 }
pub fn reversed8(x:u8) bool { return 57<x || 48>x }
pub fn exclusive8(x:u8) bool { return x>47 && x<58 }
pub fn inclusive8(x:u8) bool { return x<=47 || x>=58 }
pub fn digit(x:u8) u8 { if x<48 || x>57 { return 255 }
return x-48 }
pub fn range16(x:u16) bool { if x>=123 && x<=60000 { return true }
return false }
pub fn range32(x:u32) bool { return x<100000 || x>4000000000 }
pub fn range64(x:u64) bool { if x>=18446744073709551500 && x<=18446744073709551614 { return true }
return false }
pub fn empty8(x:u8) bool { return x>200 && x<100 }
pub fn signed(x:i64) bool { return x>=-10 && x<=10 }
events:u64
fn tick(x:u64) u64 { events+=1
return x }
pub fn effectful(x:u64) bool { return tick(x)<48 || tick(x)>57 }
pub fn event_count() u64 { return events }
pub fn reset_events() { events=0 }
pub fn addressed(x:u64) bool { p:=&x
return p.*<48 || p.*>57 }
pub fn threshold(a:u64,b:u64) bool { if a>1844674407370955161 || (a==1844674407370955161 && b>5) { return true }
return false }
pub fn small_threshold(a:u64,b:u64) bool { if a>9 || (a==9 && b>5) { return true }
return false }
pub fn reversed_threshold(a:u64,b:u64) bool { if 9<a || (9==a && b>5) { return true }
return false }
pub fn signed_threshold(a:i64,b:u64) bool { if a> -9 || (a== -9 && b>5) { return true }
return false }
pub fn disturbed(a:u64,b:u64) bool { if a>9 { return true }
events+=1
return a==9 && b>5 }
pub fn changed(a:u64,b:u64) bool { if a>9 { return true }
a+=1
if a==9 && b>5 { return true }
return false }
pub fn joined(a:u64,b:u64,choose:bool) bool {
 if choose { if a>9 { return true } } else { if b>11 { return false } }
 if a==9 && b>5 { return true }
 return false
}
'''


def main():
    if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64','amd64','aarch64','riscv64'):
        print('SKIP unsigned range tests: requires a supported native Linux host')
        return
    rng = random.Random(20261024)
    specs = {
        'outside8': (ctypes.c_uint8, list(range(256)), lambda x:x<48 or x>57),
        'inside8': (ctypes.c_uint8, list(range(256)), lambda x:48<=x<=57),
        'reversed8': (ctypes.c_uint8, list(range(256)), lambda x:x<48 or x>57),
        'exclusive8': (ctypes.c_uint8, list(range(256)), lambda x:47<x<58),
        'inclusive8': (ctypes.c_uint8, list(range(256)), lambda x:x<=47 or x>=58),
        'range16': (ctypes.c_uint16, [0,122,123,124,59999,60000,60001,65535]+[rng.getrandbits(16) for _ in range(500)], lambda x:123<=x<=60000),
        'range32': (ctypes.c_uint32, [0,99999,100000,100001,3999999999,4000000000,4000000001,2**32-1]+[rng.getrandbits(32) for _ in range(500)], lambda x:x<100000 or x>4000000000),
        'range64': (ctypes.c_uint64, [0,2**63,18446744073709551499,18446744073709551500,18446744073709551614,2**64-1]+[rng.getrandbits(64) for _ in range(500)], lambda x:18446744073709551500<=x<=18446744073709551614),
        'empty8': (ctypes.c_uint8, list(range(256)), lambda x:False),
        'signed': (ctypes.c_int64, [-2**63,-11,-10,-1,0,1,10,11,2**63-1], lambda x:-10<=x<=10),
        'addressed': (ctypes.c_uint64, [0,47,48,57,58,2**64-1], lambda x:x<48 or x>57),
    }
    with tempfile.TemporaryDirectory(prefix='dyn-range-tests-') as temp:
        work = Path(temp)
        (work/'main.dyn').write_text(SOURCE)
        for mode in ('ssa','tree'):
            env = dict(os.environ,DYN_SDK=str(ROOT),DYN_NO_SSA='1' if mode=='tree' else '0')
            lib = work/(mode+'.so')
            p = subprocess.run([DYN,'build',str(work),'--shared','--release','--opt-level','3','--cpu','generic','--no-cache','--quiet','--opt-remarks','--output',str(lib)],env=env,capture_output=True,text=True,timeout=120)
            assert p.returncode==0,p.stderr
            selected = set(re.findall(r'remark: (\w+): combined unsigned range test',p.stderr))
            assert selected == set(),p.stderr
            dll = ctypes.CDLL(str(lib));checks=0
            for name,(ctype,values,oracle) in specs.items():
                f=getattr(dll,name);f.argtypes=[ctype];f.restype=ctypes.c_bool
                for x in values:
                    assert f(x)==oracle(x),(mode,name,x,oracle(x));checks+=1
            dll.event_count.restype=ctypes.c_uint64
            dll.digit.argtypes=[ctypes.c_uint8];dll.digit.restype=ctypes.c_uint8
            for x in range(256):assert dll.digit(x)==(x-48 if 48<=x<=57 else 255),x
            dll.effectful.argtypes=[ctypes.c_uint64];dll.effectful.restype=ctypes.c_bool
            for x in (0,47,48,57,58,2**64-1):
                dll.reset_events();assert dll.effectful(x)==(x<48 or x>57)
                assert dll.event_count()==(1 if x<48 else 2),(mode,x)
            for name,ctype,limit in [('threshold',ctypes.c_uint64,1844674407370955161),('small_threshold',ctypes.c_uint64,9),('reversed_threshold',ctypes.c_uint64,9),('signed_threshold',ctypes.c_int64,-9),('disturbed',ctypes.c_uint64,9)]:
                f=getattr(dll,name);f.argtypes=[ctype,ctypes.c_uint64];f.restype=ctypes.c_bool
                values=[limit-1,limit,limit+1,0,1,2**63-1]
                if ctype==ctypes.c_int64: values += [-2**63,-1]
                else: values += [2**63,2**64-1]
                for a in values:
                    for b in (0,4,5,6,2**64-1):
                        dll.reset_events();assert f(a,b)==(a>limit or (a==limit and b>5)),(mode,name,a,b)
                        if name=='disturbed':assert dll.event_count()==(0 if a>9 else 1)
            dll.changed.argtypes=[ctypes.c_uint64,ctypes.c_uint64];dll.changed.restype=ctypes.c_bool
            dll.joined.argtypes=[ctypes.c_uint64,ctypes.c_uint64,ctypes.c_bool];dll.joined.restype=ctypes.c_bool
            for a in (0,8,9,10,2**64-1):
                for b in (0,5,6,12,2**64-1):
                    assert dll.changed(a,b)==(a>9 or (a==8 and b>5)),(mode,a,b)
                    for choose in (False,True):
                        expected=True if choose and a>9 else False if not choose and b>11 else a==9 and b>5
                        assert dll.joined(a,b,choose)==expected,(mode,a,b,choose)
            if mode=='ssa' and platform.machine().lower() in ('x86_64','amd64') and shutil.which('objdump'):
                asm=subprocess.check_output(['objdump','-d','-Mintel',str(lib)],text=True,timeout=20)
                for name in ('threshold','small_threshold','reversed_threshold','signed_threshold'):
                    body=re.search(r'<'+name+r'>:\n(.*?)(?=\n\n|\Z)',asm,re.S)
                    assert body and len(re.findall(r'\bcmp\b',body[1]))==2,(name,body[1] if body else asm)
            print(f'PASS comparison flags {mode}: {checks} values, threshold flags and exact short-circuit counts',flush=True)



if __name__ == '__main__':
    main()
