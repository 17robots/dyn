#!/usr/bin/env python3
"""Production SSA32 descriptor ABI: both hard targets, SSA and tree.

String/slice results and any parameters are supported. Any returns are rejected
by production sema; a backend-only probe requiring a frontend bypass is omitted.
No test compiler or diagnostic bypass is used. C oracles use explicit scalar
physical words/packed u64 results, never ordinary C struct calling conventions.
The assembly identity shim returns the Dyn descriptor in a0:a1 / r0:r1.

ROOT/DYN/CLANG and DYN_QEMU_RISCV32/DYN_QEMU_ARM follow sibling suites.
Container command prefixes must mount TMPDIR at the same path and use a guest
timeout (e.g. timeout 20). Host subprocesses are also bounded; temporary files
are cleaned on success or failure.
"""
import importlib.util
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(os.environ.get('ROOT', Path(__file__).resolve().parents[1])).resolve()
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
CLANG = shlex.split(os.environ.get('CLANG', 'clang'))

def sibling(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/'tests'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

b = sibling('bare-ssa')
calls = sibling('bare-ssa-calls')

SOURCE = r'''
use "std/io"
extern fn oracle() u32
extern fn cdesc_addr() rawptr
fn cdesc(x:[]const u8) []const u8 { return #cast(fn([]const u8) []const u8,cdesc_addr())(x) }
extern fn ccheck_addr() rawptr
fn ccheck(x:any) u32 { return #cast(fn(any) u32,ccheck_addr())(x) }
extern fn cmany_addr() rawptr
fn cmany(a:u32,b:u32,c:u32,d:u32,e:u32,f:u32,g:u32,x:any,y:[]const u8,z:any) u32 { return #cast(fn(u32,u32,u32,u32,u32,u32,u32,any,[]const u8,any) u32,cmany_addr())(a,b,c,d,e,f,g,x,y,z) }
pub fn desc(x:[]const u8) []const u8 { return cdesc(x) }
pub fn slice(x:[]u8) []u8 { return x }
pub fn indirect(p:fn([]const u8) []const u8,x:[]const u8) []const u8 { return p(x) }
pub fn anyround(x:any) u32 { return ccheck(x) }
pub fn first(x:[]const u8) u8 { return cdesc(x)[0] }
pub fn partial(x:[]const u8) usize { return #len(cdesc(x)) }
pub fn unused(x:[]const u8,y:any) { _=cdesc(x) }
pub fn many(a:u32,b:u32,c:u32,d:u32,e:u32,f:u32,g:u32,x:any,y:[]const u8,z:any) u32 { return cmany(a,b,c,d,e,f,g,x,y,z) }
pub fn cycle(x:[]const u8,y:[]const u8,n:u32) []const u8 { a:=x b:=y i:u32=0 for i<n { t:=a a=b b=t i=#wrap(i+1) } return a }
pub fn localdesc(x:[]const u8) []const u8 { a:=x p:=&a p.*=cdesc(p.*) return a }
state:[]const u8
pub fn mutate() []const u8 { state="changed" return state }
extern fn paircheck_addr() rawptr
fn paircheck(x:[]const u8,y:[]const u8) u32 { return #cast(fn([]const u8,[]const u8) u32,paircheck_addr())(x,y) }
pub fn isolation(x:[]const u8) u32 { state=x return paircheck(state,mutate()) }
fn main() { r:=oracle() if r!=0 { _=io.println(io.stdout(),"oracle {}",r) #panic("oracle") } _=io.write_all(io.stdout(),"DESCRIPTORS OK\n") }
extern fn touch(p:rawptr)
pub fn large(x:[]const u8) []const u8 { a:[1025]u64=[] touch(&a) return cdesc(x) }
pub fn protecteddesc(x:[]const u8) []const u8 { defer { state="cleanup" } return cdesc(x) }
pub fn rawarg(x:[2]u64) u64 { return x[0] }
'''

C_SOURCE = r'''extern unsigned capacitycallee(void),capacitycall(void*,unsigned,unsigned);
extern unsigned long long large(unsigned,unsigned),protecteddesc(unsigned,unsigned);

typedef unsigned W; typedef unsigned long long U;
/* Explicit physical ABI: two W arguments, result bits in r0:r1/a0:a1.
   These declarations intentionally do not use a C struct ABI. */
extern U desc(W,W),slice(W,W),indirect(void*,W,W),cycle(W,W,W,W,W),localdesc(W,W);
extern W first(W,W),partial(W,W),anyround(U,W),many(W,W,W,W,W,W,W,U,W,W,W,U,W),isolation(W,W);
extern void unused(W,W,U,W);

static unsigned char data[8]={11,22,33,44,55,66,77,88};
extern U cdesc(W p,W n);
W ccheck(U tag,W p) { return tag==0xfedcba9876543210ULL && p==(W)data ? 1:1000; }
/* Seven scalar words put the first any tag across a7/stack on RV32.
   Thumb rounds its u64 tag to an even pair, spilling it after r0-r3.
   Distinct second tag/pointer and intervening descriptor check group offsets. */
W cmany(W a,W b,W c,W d,W e,W f,W g,U tag,W p,W text,W n,U tag2,W p2) {
 return a==1 && b==2 && c==3 && d==4 && e==5 && f==6 && g==7 &&
 tag==0xfedcba9876543210ULL && p==(W)data && text==(W)data && n==8 && tag2==0x8877665544332211ULL && p2==(W)(data+1) ? 0:100;
}
W paircheck(W p,W n,W q,W m) {return p==(W)data && n==8 && m==7 && ((char*)q)[0]=='c'?0:101;}
W oracle(void) {
 if(capacitycall(capacitycallee,(W)data,8)!=16)return 99;
 W p=(W)data;U expected=(U)p|((U)8<<32),tag=0xfedcba9876543210ULL;
 if(large(p,8)!=expected || protecteddesc(p,8)!=expected || desc(p,8)!=expected || slice(p,8)!=expected || indirect(cdesc,p,8)!=expected || localdesc(p,8)!=expected) return 1;
 if(first(p,8)!=11 || partial(p,8)!=8 || anyround(tag,p)!=1) return 2;
 unused(p,8,tag,p);
 if(many(1,2,3,4,5,6,7,tag,p,p,8,0x8877665544332211ULL,p+1)) return 3;
 if(cycle(p,8,p+1,7,3)!=((U)(p+1)|((U)7<<32)) || cycle(p,8,p+1,7,4)!=expected) return 4;
 if(isolation(p,8))return 7;
 return 0;
}

void *cdesc_addr(void) { return (void*)cdesc; }

void *ccheck_addr(void) { return (void*)ccheck; }

void *cmany_addr(void) { return (void*)cmany; }

void *paircheck_addr(void) { return (void*)paircheck; }
void touch(void *p) { volatile unsigned *q=p; q[0]=1; }
'''

POSITIVE = ['protecteddesc', 'rawarg', 'first', 'desc', 'slice', 'indirect', 'anyround', 'partial', 'unused', 'many', 'cycle', 'localdesc', 'mutate', 'isolation', 'large', 'capacitycallee', 'capacitycall', 'cdesc', 'ccheck', 'cmany', 'paircheck']
FALLBACK = []
# 256 descriptors = 512 flattened operands plus the indirect target. Capture
# the incoming bank before reconstruction; use both ends of the spilled bank.
types = ','.join(['[]const u8'] * 256)
params = ','.join(f'a{i}:[]const u8' for i in range(256))
args = ','.join(['x'] * 256)
SOURCE += f'\npub fn capacitycallee({params}) usize {{ return #len(a0)+#len(a255) }}\npub fn capacitycall(p:fn({types}) usize,x:[]const u8) usize {{ return p({args}) }}\n'

RV_SHIM = '.text\n.globl cdesc\ncdesc: ret\n'
ARM_SHIM = '.syntax unified\n.thumb\n.eabi_attribute 28,1\n.text\n.global cdesc\n.thumb_func\ncdesc: bx lr\n'


def check_remarks(log, mode):
    if mode == 'tree':
        assert 'SSA code generation' not in log, log
        return
    for name in POSITIVE + FALLBACK:
        messages = re.findall(r'^remark: ' + re.escape(name) + r': (.*)$', log, re.M)
        if name in POSITIVE:
            assert any(m.startswith('SSA code generation,') for m in messages), (name, messages)
            assert not any('tree emitter' in m for m in messages), (name, messages)
        else:
            assert 'tree emitter (paired SSA boundary)' in messages, (name, messages)
            assert not any('SSA code generation' in m for m in messages), (name, messages)


def negative_controls():
    remarks = {n: f'remark: {n}: SSA code generation, test' for n in POSITIVE}
    remarks.update({n: f'remark: {n}: tree emitter (paired SSA boundary)' for n in FALLBACK})
    check_remarks('\n'.join(remarks.values()), 'ssa')
    bad = [('ssa', '\n'.join(v for k, v in remarks.items() if k != n)) for n in remarks]
    bad += [('ssa', '\n'.join(remarks.values()) + f'\nremark: {n}: tree emitter (paired SSA boundary)') for n in POSITIVE]
    bad += [('ssa', '\n'.join(remarks.values()) + f'\nremark: {n}: SSA code generation, test') for n in FALLBACK]
    bad += [('tree', '\n'.join(remarks.values()))]
    for mode, log in bad:
        try:
            check_remarks(log, mode)
        except AssertionError:
            continue
        raise AssertionError('lowering negative control accepted')
    return len(bad)


def main():
    controls = negative_controls()
    for label, command in [('DYN', [DYN]), ('CLANG', CLANG)]:
        if not command or not shutil.which(command[0]):
            print(f'SKIP descriptors: {label} unavailable: {command}', flush=True)
            return
    completed = rejected = 0
    for target, variable, program, flags, board in b.TARGETS:
        qemu = shlex.split(os.environ.get(variable, '')) or [program]
        if not shutil.which(qemu[0]):
            print(f'SKIP {target}: {qemu[0]} unavailable; set {variable}', flush=True)
            continue
        with tempfile.TemporaryDirectory(prefix='dyn-ssa-descriptors-') as temporary:
            work = Path(temporary)
            project = work/'source'
            project.mkdir()
            (work/'oracle.c').write_text(C_SOURCE)
            (work/'shim.S').write_text(ARM_SHIM if target.startswith('thumb') else RV_SHIM)
            links = []
            for filename in ('oracle.c', 'shim.S'):
                obj = work/(filename + '.o')
                subprocess.run([*CLANG, *flags, '-ffreestanding', '-fno-stack-protector', '-O2',
                                '-c', str(work/filename), '-o', str(obj)], check=True, timeout=60)
                if target.startswith('thumb'):
                    b.arm_addends(obj)
                links += ['--link', str(obj)]
            for mode in ('ssa', 'tree'):
                env = dict(os.environ)
                env.pop('DYN_NO_SSA', None)
                if mode == 'tree':
                    env['DYN_NO_SSA'] = '1'
                image = work/f'{mode}.elf'
                command = [DYN, 'build', str(project), '--release', '--target', target,
                           '--no-cache', '--opt-remarks', '--output', str(image)]
                (project/'main.dyn').write_text(SOURCE)
                result = subprocess.run([*command, *links], env=env, capture_output=True, text=True, timeout=120)
                log = result.stdout + result.stderr
                assert result.returncode == 0, (target, mode, log)
                check_remarks(log, mode)
                actual = calls.run_guest([*qemu, *board, '-nographic', '-kernel', str(image)])
                assert actual == (0, b'DESCRIPTORS OK\n', b''), (target, mode, actual)
                completed += 1
                (project/'main.dyn').write_text('pub fn rejected(x:any) any { return x }\nfn main() {}\n')
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120)
                assert result.returncode != 0 and 'returning any would escape borrowed storage' in result.stdout + result.stderr, (target, mode, result)
                rejected += 1
            print(f'PASS {target}: SSA/tree exact output; {len(POSITIVE)} named SSA, {len(FALLBACK)} fallback; any-return rejected in both modes', flush=True)
    print(f'{"PASS" if completed else "SKIP"} descriptors: {completed}/4 guests; {rejected}/4 frontend negatives; {controls} lowering negative controls', flush=True)


if __name__ == '__main__':
    main()
