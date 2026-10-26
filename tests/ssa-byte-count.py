#!/usr/bin/env python3
"""Generic checked byte-count loops: exact SIMD bounds and scalar overflow."""
from pathlib import Path
import os
import platform
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'amd64'):
    print('SKIP SSA byte count: Linux x64 execution fixture')
    raise SystemExit(0)


def run(args, **kwargs):
    return subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=120, **kwargs)


FUNCTIONS = r'''
pub fn count_eq(source:[]const u8, initial:u64) u64 {
 count:=initial
 for i in 0..#len(source) { if source[i]==34 { count+=1 } }
 return count
}
pub fn count_lt(source:[]const u8, initial:u64) u64 {
 count:=initial
 for i in 0..#len(source) { if source[i]<128 { count+=1 } }
 return count
}
pub fn count_usize(source:[]const u8, initial:usize) usize {
 count:=initial
 for i in 0..#len(source) { if source[i]==34 { count+=1 } }
 return count
}
pub fn count_union(source:[]const u8, initial:u64) u64 {
 count:=initial
 for i in 0..#len(source) { b:=source[i]
 if b==34 || b==92 || b<32 { count+=1 } }
 return count
}
pub fn count_rounds(p:*const u8,n:usize,rounds:usize) u64 {
 source:=p[..n]
 count:u64=0
 for round in 0..rounds {
  for i in 0..n { b:=source[i]
  if b=='"' || b=='\\' || b<32 { count+=1 } }
 }
 return count
}
pub fn count_live(source:[]const u8,initial:u64,a,b,c,d,e,f,g,h:f64) f64 {
 count:=initial
 for i in 0..#len(source) { if source[i]<128 { count+=1 } }
 return a+b*2.0+c*3.0+d*4.0+e*5.0+f*6.0+g*7.0+h*8.0+#cast(f64,count)
}
pub fn count_low(source:[]const u8) u64 {
 count:u64=0
 for i in 0..#len(source) { if source[i]<1 { count+=1 } }
 return count
}
pub fn count_high(source:[]const u8) u64 {
 count:u64=0
 for i in 0..#len(source) { if source[i]<255 || source[i]==255 { count+=1 } }
 return count
}
pub fn count_duplicate(source:[]const u8) u64 {
 count:u64=0
 for i in 0..#len(source) { if source[i]==34 || source[i]<128 { count+=1 } }
 return count
}
'''

INVERSE_PREDICATES = {
    'count_ne0': ('b!=0', 'p[i]!=0'),
    'count_ne255': ('b!=255', 'p[i]!=255'),
    # A character literal preserves the valid zero-threshold IR shape;
    # the frontend diagnoses the integer-literal spelling b >= 0.
    'count_ge0': ("b>='\\x00'", 'p[i]>=0'),
    'count_ge1': ('b>=1', 'p[i]>=1'),
    'count_ge128': ('b>=128', 'p[i]>=128'),
    'count_ge255': ('b>=255', 'p[i]>=255'),
    'count_inverse_first': ('b!=34 || b==34', 'p[i]!=34 || p[i]==34'),
    'count_inverse_last': ('b==34 || b>=128', 'p[i]==34 || p[i]>=128'),
    'count_inverse_overlap': ('b>=128 || b!=0 || b>=255', 'p[i]>=128 || p[i]!=0 || p[i]>=255'),
}
for name, (predicate, _) in INVERSE_PREDICATES.items():
    FUNCTIONS += f'''pub fn {name}(source:[]const u8,initial:u64) u64 {{
 count:=initial
 for i in 0..#len(source) {{ b:=source[i]
 if {predicate} {{ count+=1 }} }}
 return count
}}
'''
FUNCTIONS += '''pub fn count_inverse_live(source:[]const u8,initial:u64,a,b,c,d,e,f,g,h:f64) f64 {
 count:=initial
 for i in 0..#len(source) { if source[i]>=128 { count+=1 } }
 return a+b*2.0+c*3.0+d*4.0+e*5.0+f*6.0+g*7.0+h*8.0+#cast(f64,count)
}
'''

NEGATIVE = r'''
extern fn effect(value:u8) bool
extern fn expose(value:*u64)
pub fn rejected_exposed(source:[]const u8) u64 {
 count:u64=0
 expose(&count)
 for i in 0..#len(source) { if source[i]==34 { count+=1 } }
 return count
}
pub fn rejected_call(source:[]const u8) u64 {
 count:u64=0
 for i in 0..#len(source) { if effect(source[i]) { count+=1 } }
 return count
}
pub fn rejected_narrow(source:[]const u8) u8 {
 count:u8=0
 for i in 0..#len(source) { if source[i]==34 { count+=1 } }
 return count
}
pub fn rejected_partial(source:[]const u8,n:usize) u64 {
 count:u64=0
 for i in 0..n { if source[i]==34 { count+=1 } }
 return count
}
pub fn rejected_signed(source:[]const u8) i64 {
 count:i64=0
 for i in 0..#len(source) { if source[i]==34 { count+=1 } }
 return count
}
pub fn rejected_wrap(source:[]const u8) u64 {
 count:u64=0
 for i in 0..#len(source) { if source[i]==34 { count=#wrap(count+1) } }
 return count
}
pub fn rejected_cleanup(source:[]const u8) u64 {
 defer { _=effect(3) }
 count:u64=0
 for i in 0..#len(source) { if source[i]==34 { count+=1 } }
 return count
}
pub fn rejected_mutated_stop(p:*const u8,n:usize,rounds:usize) u64 {
 source:=p[..n]
 stop:=n
 count:u64=0
 for round in 0..rounds {
  for i in 0..stop { if source[i]==34 { count+=1 } }
  if stop>0 { stop-=1 }
 }
 return count
}
pub fn rejected_mutated_source(p:*const u8,n:usize,rounds:usize) u64 {
 source:=p[..n]
 count:u64=0
 for round in 0..rounds {
  for i in 0..n { if source[i]==34 { count+=1 } }
  source=p[..n]
 }
 return count
}
'''

C = r'''
#include <stdint.h>
#include <stddef.h>
#ifndef FAIL
#define FAIL 0
#endif
static long call6(long n,long a,long b,long c,long d,long e,long f){
 register long r10 __asm__("r10")=d;register long r8 __asm__("r8")=e;register long r9 __asm__("r9")=f;
 long r;__asm__ volatile("syscall":"=a"(r):"a"(n),"D"(a),"S"(b),"d"(c),"r"(r10),"r"(r8),"r"(r9):"rcx","r11","memory");return r;
}
extern uint64_t count_eq(const uint8_t*,size_t,uint64_t);
extern uint64_t count_lt(const uint8_t*,size_t,uint64_t);
extern size_t count_usize(const uint8_t*,size_t,size_t);
extern uint64_t count_union(const uint8_t*,size_t,uint64_t);
extern uint64_t count_rounds(const uint8_t*,size_t,size_t);
extern uint64_t count_low(const uint8_t*,size_t);
extern uint64_t count_high(const uint8_t*,size_t);
extern uint64_t count_duplicate(const uint8_t*,size_t);
extern double count_live(const uint8_t*,size_t,uint64_t,double,double,double,double,double,double,double,double);
_Bool effect(uint8_t x){return x==34;}
void expose(uint64_t*p){*p=1;}
static unsigned hit(unsigned b){return b==34||b==92||b<32;}
static int check(const uint8_t*p,size_t n){
 uint64_t eq=0,lt=0,un=0,low=0;
 for(size_t i=0;i<n;i++){eq+=p[i]==34;lt+=p[i]<128;un+=hit(p[i]);low+=p[i]<1;}
 if(count_eq(p,n,17)!=17+eq||count_lt(p,n,17)!=17+lt||count_union(p,n,17)!=17+un)return 1;
 if(count_usize(p,n,17)!=17+eq)return 6;
 if(count_low(p,n)!=low||count_high(p,n)!=n||count_duplicate(p,n)!=lt)return 2;
 if(count_live(p,n,17,1,2,3,4,5,6,7,8)!=221+(double)lt)return 3;
 if(p&&count_rounds(p,n,3)!=3*un)return 4;
 return 0;
}
int oracle(void){
 uint8_t*map=(void*)call6(9,0,12288,0,0x22,-1,0);
 if((intptr_t)map<0||call6(10,(long)(map+4096),4096,3,0,0,0))return 90;
 if(FAIL==1){for(size_t i=0;i<64;i++)map[4096+i]=34;count_union(map+4096,64,UINT64_MAX-31);return 91;}
 if(FAIL==2){map[8191]=34;count_eq(map+8191,64,UINT64_MAX);return 92;}
 if(FAIL==3){map[8191]=0;count_lt(map+8191,64,UINT64_MAX);return 93;}
 if(FAIL==4){map[8191]=1;count_ge1(map+8191,64,UINT64_MAX);return 94;}
 if(FAIL==5){for(size_t i=0;i<64;i++)map[4096+i]=0;count_ne255(map+4096,64,UINT64_MAX-31);return 95;}
 if(check(0,0)||count_eq(0,0,UINT64_MAX)!=UINT64_MAX)return 5;
 for(size_t n=0;n<=129;n++)for(size_t pad=0;pad<=16;pad++)for(unsigned b=0;b<256;b++){
  uint8_t*p=map+4096+pad;
  for(size_t i=0;i<n;i++)p[i]=(uint8_t)(i*73+b);
  if(n)p[n/2]=(uint8_t)b;
  int r=check(p,n);if(r)return 10+r;
 }
 for(size_t n=0;n<=129;n++)for(unsigned b=0;b<256;b++){
  uint8_t*p=map+8192-n;
  for(size_t i=0;i<n;i++)p[i]=(uint8_t)b;
  int r=check(p,n);if(r)return 20+r;
 }
 for(size_t n=0;n<=64;n++)for(unsigned gap=0;gap<=64;gap++){
  uint8_t*p=map+8192-n;for(size_t i=0;i<n;i++)p[i]=i%3==0?34:255;
  uint64_t matches=(n+2)/3;
  if(matches<=gap&&count_union(p,n,UINT64_MAX-gap)!=UINT64_MAX-gap+matches)return 30;
 }
 call6(11,(long)map,12288,0,0,0,0);return 0;
}
'''
C = C.replace('_Bool effect', ''.join(
    f'extern uint64_t {name}(const uint8_t*,size_t,uint64_t);\n' for name in INVERSE_PREDICATES
) + 'extern double count_inverse_live(const uint8_t*,size_t,uint64_t,double,double,double,double,double,double,double,double);\n_Bool effect', 1)
inverse_checks = []
for number, (name, (_, predicate)) in enumerate(INVERSE_PREDICATES.items()):
    inverse_checks.append(f'{{uint64_t expected=0;for(size_t i=0;i<n;i++)expected+=({predicate});'
                          f'if({name}(p,n,17)!=17+expected||{name}(p,n,UINT64_MAX-n)!=UINT64_MAX-n+expected)return {40+number};}}')
inverse_checks.append('if(count_inverse_live(p,n,17,1,2,3,4,5,6,7,8)!=221+(double)(n-lt))return 49;')
C = C.replace(' if(count_usize', '\n'.join(inverse_checks) + '\n if(count_usize', 1)

with tempfile.TemporaryDirectory(prefix='dyn-byte-count-') as temporary:
    work = Path(temporary)
    project = work / 'project'
    project.mkdir()
    (project / 'main.dyn').write_text(FUNCTIONS + NEGATIVE + '''
extern fn oracle() i32
fn main() { if oracle()!=0 { #panic("byte count oracle") } }
''')
    (work / 'oracle.c').write_text(C)
    outcomes = {}
    for mode in ('ssa', 'tree', 'o2'):
        env = dict(os.environ, DYN_NO_SSA='1' if mode == 'tree' else '0')
        for failure in range(6):
            obj = work / f'oracle-{failure}.o'
            p = run([os.environ.get('CC', 'cc'), '-O2', '-ffreestanding', '-fno-stack-protector', f'-DFAIL={failure}', '-c', work / 'oracle.c', '-o', obj])
            assert p.returncode == 0, p.stderr
            binary = work / f'{mode}-{failure}'
            p = run([DYN, 'build', project, '--release', '--opt-level', '2' if mode == 'o2' else '3', '--cpu', 'generic', '--no-cache', '--opt-remarks', '--emit-object', '--link', obj, '--output', binary], env=env)
            assert p.returncode == 0, (mode, failure, p.stdout, p.stderr)
            if failure == 0:
                selected = set(re.findall(r'remark: (\w+): vectorized byte predicate count', p.stderr))
                expected = {'count_eq', 'count_lt', 'count_usize', 'count_union', 'count_rounds', 'count_live', 'count_low', 'count_high', 'count_duplicate'}
                expected |= set(INVERSE_PREDICATES) | {'count_inverse_live'}
                assert selected == (expected if mode == 'ssa' else set()), (mode, selected, p.stderr)
                asm = run(['objdump', '-d', '-Mintel', str(binary) + '.o'])
                assert asm.returncode == 0, asm.stderr
                assert ('psadbw' in asm.stdout) == (mode == 'ssa'), mode
                if mode == 'ssa':
                    union = re.search(r'<count_union>:\n(.*?)(?=\n[0-9a-f]+ <|\Z)', asm.stdout, re.S)
                    assert union, asm.stdout
                    # Equality predicates retain the loaded input vector. The
                    # final unsigned predicate uses one saturating subtract,
                    # rather than another load and two biased broadcasts.
                    assert union[1].count('movdqu') == 1, union[1]
                    assert union[1].count('psubusb') == 1, union[1]
                    assert 'pcmpgtb' not in union[1], union[1]
            p = run([binary])
            outcomes[mode, failure] = (p.returncode, p.stdout, p.stderr)
            if failure == 0:
                assert p.returncode == 0, (mode, p.returncode, p.stdout, p.stderr)
            else:
                assert p.returncode == 101 and 'overflow' in p.stdout + p.stderr, (mode, failure, p.returncode, p.stdout, p.stderr)
        print(f'PASS byte count {mode}: predicates, exact extents, page tails, live FP, rounds, near-overflow, precise overflow')
    for failure in range(6):
        assert outcomes['ssa', failure] == outcomes['tree', failure], (failure, outcomes)
        assert outcomes['ssa', failure] == outcomes['o2', failure], (failure, outcomes)
    print('PASS byte count admission controls and exact SSA/tree overflow diagnostics')
    budget_project = work / 'budget'
    budget_project.mkdir()
    (budget_project / 'main.dyn').write_text('''extern fn effect(value:u8) bool
pub fn rejected_proof_budget(p:*const u8,n:usize,rounds:usize) u64 {
 source:=p[..n]
 count:u64=0
 for round in 0..rounds {
  for i in 0..n { if source[i]==34 { count+=1 } }
''' + '_=effect(34)\n' * 2100 + '''
 }
 return count
}
''')
    p = run([DYN, 'build', budget_project, '--release', '--opt-level', '3', '--cpu', 'generic', '--no-cache', '--opt-remarks', '--shared', '--emit-object', '--output', work / 'budget.so'], env=dict(os.environ, DYN_NO_SSA='0'))
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert 'vectorized byte predicate count' not in p.stderr, p.stderr
    assert 'rejected_proof_budget: SSA code generation' in p.stderr, p.stderr
    print('PASS byte count: bounded invariant-proof work declines oversized traversal')
    clang = shutil.which(os.environ.get('CLANG', 'clang'))
    wine = shutil.which('wine')
    if clang:
        begin = C.index('static long call6(')
        end = C.index('\nextern uint64_t count_eq', begin)
        adapter = '''extern void *dyn_win_virtual_alloc(void*,uint64_t,uint32_t,uint32_t);
extern int32_t dyn_win_virtual_free(void*,uint64_t,uint32_t);
static long long call6(long long n,long long a,long long b,long long c,long long d,long long e,long long f){
 (void)b;(void)c;(void)d;(void)e;(void)f;
 if(n==9)return (long long)dyn_win_virtual_alloc(0,12288,0x2000,1);
 if(n==10)return dyn_win_virtual_alloc((void*)a,4096,0x1000,4)?0:-1;
 if(n==11){dyn_win_virtual_free((void*)a,0,0x8000);return 0;}return -1;
}
'''
        portable = C[:begin] + adapter + C[end:]
        portable = re.sub(r'(?<!long )\blong\b(?! long)', 'long long', portable)
        (work / 'windows.c').write_text(portable)
        for mode in ('ssa', 'tree'):
            env = dict(os.environ, DYN_NO_SSA='1' if mode == 'tree' else '0', WINEDEBUG='-all')
            for failure in range(6):
                obj = work / f'windows-{failure}.o'
                p = run([clang, '--target=x86_64-pc-windows-msvc', '-O2', '-ffreestanding', '-fno-stack-protector', f'-DFAIL={failure}', '-c', work / 'windows.c', '-o', obj])
                assert p.returncode == 0, p.stderr
                binary = work / f'windows-{mode}-{failure}.exe'
                p = run([DYN, 'build', project, '--target', 'x86_64-windows', '--release', '--opt-level', '3', '--cpu', 'generic', '--no-cache', '--opt-remarks', '--link', obj, '--output', binary], env=env)
                assert p.returncode == 0, (mode, p.stdout, p.stderr)
                selected = set(re.findall(r'remark: (\w+): vectorized byte predicate count', p.stderr))
                assert selected == (expected if mode == 'ssa' else set()), (mode, selected)
                if wine:
                    p = run([wine, binary], env=env)
                    assert (p.returncode == 0 if failure == 0 else p.returncode != 0 and 'overflow' in p.stdout + p.stderr), (mode, failure, p.returncode, p.stdout, p.stderr)
            print(f'PASS Win64 byte count {mode}: cross-build, named selection' + (', guarded oracle and live FP via Wine' if wine else ' (runtime SKIP: Wine unavailable)'))
    else:
        print('SKIP Win64 byte count: Clang unavailable')
