#!/usr/bin/env python3
"""Case dispatch: 24 production guests and 32 separate backend-adapter guests.

Literal C expectations are independent of Dyn/tree results. The adapter changes
validated IR only; production frontend rejection is tested separately. It needs
release compiler objects (tools/build.py dyn-release); absence explicitly SKIPs
only adapter coverage. ROOT, BUILD, DYN, CC, CLANG, TMPDIR and DYN_QEMU_ARM/
RISCV32 are portable overrides. Container prefixes must mount TMPDIR identically
and bound their own guests. All generated artifacts are temporary.
"""
import importlib.util
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import tempfile

ROOT = Path(os.environ.get('ROOT', Path(__file__).resolve().parents[1])).resolve()
BUILD = Path(os.environ.get('BUILD', ROOT/'build')).resolve()
DYN = str(Path(os.environ.get('DYN', BUILD/'dyn-release')).resolve())
CLANG = shlex.split(os.environ.get('CLANG', 'clang'))
CC = shlex.split(os.environ.get('CC', 'cc'))


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tests'/f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


b = module('bare-ssa')
soft = module('bare-ssa-soft')

SOURCE = r'''
use "std/io"
enum Key { A,B,C,D,E }
pub fn dense(x:i64) i64 { case x { -2=>{return 12},-1=>{return 13},0,1=>{return 21},2=>{return 22},3=>{return 23},_=>{return 99} } }
pub fn sparse(x:i64) i64 { case x { -9000000000..-8999999997=>{return 10},4294967297=>{return 20},9000000000=>{return 30},_=>{return 40} } }
pub fn high(x:u64) u64 { case x { 18446744073709551612=>{return 12},18446744073709551613,18446744073709551614=>{return 13},18446744073709551615=>{return 15},_=>{return 99} } }
pub fn first(x:i64) i64 { case x { 0..2=>{return 10},2,3,4,5=>{return 20},_=>{return 30} } }
pub fn exhaustive(x:Key) i64 { case x { Key.A=>{return 11},Key.B,Key.C=>{return 22},Key.D=>{return 33},Key.E=>{return 44} } }
pub fn enumwild(x:Key) i64 { case x { Key.A=>{return 11},_=>{return 55} } }
pub fn cycle(x:i64,n:u32) i64 { a:i64=3 b:i64=7 c:i64=11 i:u32=0 for i<n { case x { 0,1=>{t:=a a=b b=c c=t},2=>{a=17},_=>{b=19} } i=#wrap(i+1) } return a*100+b*10+c }
pub fn terminal(x:i64) i64 { case x { 1=>{return 71},9=>{return 79},_=>{return 99} } }
pub fn protected(x:Key) i64 { defer { _=io.write_all(io.stdout(),"CLEAN\n") } case x { Key.A=>{return 11},Key.B=>{return 22},Key.C=>{return 22},Key.D=>{return 33},Key.E=>{return 44} } }
extern fn oracle() u32
extern fn badtag() Key
extern fn cpacr() u32
'''
NAMES = 'dense sparse high first exhaustive enumwild cycle terminal'.split()
C_SOURCE = r'''
typedef long long I;typedef unsigned long long U;
extern I dense(I),sparse(I),first(I),exhaustive(unsigned),enumwild(unsigned),cycle(I,unsigned),terminal(I);
extern U high(U);
unsigned badtag(void){return 255;}
unsigned cpacr(void){
#ifdef __arm__
return *(volatile unsigned*)0xe000ed88u;
#else
return 0;
#endif
}
unsigned oracle(void){
I in[]={-3,-2,-1,0,1,2,3,4,4294967296LL};I want[]={99,12,13,21,21,22,23,99,99};
for(unsigned i=0;i<9;i++)if(dense(in[i])!=want[i])return 1;
if(sparse(-9000000000LL)!=10||sparse(-8999999999LL)!=10||sparse(-8999999998LL)!=10||sparse(-8999999997LL)!=40||sparse(4294967297LL)!=20||sparse(1)!=40||sparse(9000000000LL)!=30)return 2;
if(high(~0ULL-3)!=12||high(~0ULL-2)!=13||high(~0ULL-1)!=13||high(~0ULL)!=15||high(0xffffffff)!=99)return 3;
if(first(2)!=20||first(3)!=20||first(4)!=20||first(5)!=20||first(6)!=30)return 4;
I ew[]={11,22,22,33,44};for(unsigned i=0;i<5;i++)if(exhaustive(i)!=ew[i])return 5;
if(enumwild(255)!=55||cycle(0,1)!=813||cycle(1,2)!=1137||cycle(0,3)!=381||cycle(2,1)!=1781||terminal(1)!=71||terminal(9)!=79)return 6;
return 0;}
'''

# BACKEND ONLY: deliberately unreachable through accepted source syntax.
ADAPTER = r'''
#define dyn_native_object original_native_object
#include "backend/compiler.c"
#undef dyn_native_object
int dyn_native_object(const DynSource *source, const DynIrProgram *ir, const char *path, bool trace, bool info, bool shared, bool report) {
 if(getenv("SSA_CASE_IR")) for(size_t i=0;i<ir->function_count;i++) {
  const DynIrFunction *f=&ir->functions[i];
  if(!strcmp(f->name,"first")) {
   const DynIrStmt *st=&ir->statements[ir->children[f->body_start]];
   ir->patterns[ir->case_arms[st->case_arm_start].pattern_start].last=3;
  }
  if(!strcmp(f->name,"terminal")) {
   DynIrStmt *st=&ir->statements[ir->children[f->body_start]];
   st->case_arm_count=2;
  }
 }
 return original_native_object(source,ir,path,trace,info,shared,report);
}
'''


def environment(mode, adapter=False):
    env = dict(os.environ)
    env.pop('DYN_NO_SSA', None)
    env.pop('SSA_CASE_IR', None)
    if mode == 'tree':
        env['DYN_NO_SSA'] = '1'
    if adapter:
        env['SSA_CASE_IR'] = '1'
        env['DYN_SDK'] = str(ROOT)
    return env


def remarks(log, mode):
    soft.remarks(log, mode, NAMES)
    if mode == 'ssa':
        messages = re.findall(r'^remark: protected: (.*)$', log, re.M)
        assert any('SSA code generation' in m for m in messages), log
        assert not any('tree emitter' in m for m in messages), log


def controls():
    lines = [f'remark: {name}: SSA code generation, control' for name in NAMES]
    lines += ['remark: protected: SSA code generation, control']
    remarks('\n'.join(lines), 'ssa')
    bad = [('\n'.join(lines[:i] + lines[i+1:]), 'ssa') for i in range(len(lines))]
    bad += [('\n'.join(lines + [f'remark: {n}: tree emitter (paired SSA boundary)']), 'ssa') for n in NAMES]
    bad += [('\n'.join(lines + ['remark: protected: tree emitter (paired SSA boundary)']), 'ssa'),
            ('\n'.join(lines), 'tree')]
    for log, mode in bad:
        try:
            remarks(log, mode)
        except AssertionError:
            continue
        raise AssertionError(('lowering negative control accepted', mode, log))
    remarks('', 'tree')
    print(f'PASS cases: {len(bad)} named-remark negative controls', flush=True)


def run_guest(command):
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=10)
        raise AssertionError(f'guest exceeded 30 seconds: {command}')
    return process.returncode, stdout.replace(b'\r\n', b'\n'), stderr


def build_adapter(work):
    objects = sorted((BUILD/'obj/release').glob('*.o'))
    if not CC or not shutil.which(CC[0]) or not (BUILD/'obj/release/main.o').exists():
        print('SKIP backend adapter: requires CC and release compiler objects', flush=True)
        return None
    source = work/'adapter.c'
    source.write_text(ADAPTER)
    compiler = work/'dyn-ir'
    subprocess.run([*CC, '-std=c11', '-D_POSIX_C_SOURCE=200809L', '-O1',
                    '-I'+str(ROOT/'src'), str(source),
                    *[str(p) for p in objects if p.name != 'compiler.o'],
                    '-pthread', '-o', str(compiler)], check=True, timeout=120)
    for runtime in BUILD.glob('dynrt*.o'):
        (work/runtime.name).symlink_to(runtime.resolve())
    return str(compiler)


def frontend_negatives(work, target):
    project = work/'frontend'
    project.mkdir()
    for name, source, diagnostic in [
        ('overlap', 'case x { 0..3=>{return 10},2,3=>{return 20},_=>{return 30} }',
         'duplicate or overlapping case pattern'),
        ('nonexhaustive', 'case x { 1=>{return 71},9=>{return 79} }',
         'case is not exhaustive'),
    ]:
        (project/'main.dyn').write_text('pub fn rejected(x:i64) i64 { '+source+' }\nfn main() {}\n')
        for mode in ('ssa', 'tree'):
            result = subprocess.run([DYN, 'build', str(project), '--release', '--target', target,
                '--no-cache', '--output', str(work/'rejected.elf')], env=environment(mode),
                capture_output=True, text=True, timeout=120)
            assert result.returncode != 0 and diagnostic in result.stdout+result.stderr, (name, result)


def guests(work, compiler, target, flags, board, qemu, adapter, audit):
    work.mkdir()
    c = C_SOURCE
    if adapter:
        c = soft.replace_once(c, 'first(2)!=20||first(3)!=20', 'first(2)!=10||first(3)!=10')
    (work/'oracle.c').write_text(c)
    obj = work/'oracle.o'
    subprocess.run([*CLANG, *flags, '-ffreestanding', '-fno-stack-protector', '-O2',
                    '-c', str(work/'oracle.c'), '-o', str(obj)], check=True, timeout=60)
    if target.startswith('thumb'):
        b.arm_addends(obj)
    fixtures = [
        ('success', r'n:=oracle() if n!=0 { _=io.println(io.stdout(),"BAD {}",n) #panic("oracle") } _=io.write_all(io.stdout(),"CASES OK\n")', (0, b'CASES OK\n', b'')),
        ('invalid', '_=exhaustive(badtag())', (101, b'runtime check failed (enum.tag.ok) in exhaustive\n', b'')),
        ('protected', '_=protected(badtag())', (101, b'CLEAN\nruntime check failed (enum.tag.ok) in protected\n', b'')),
    ]
    if adapter:
        fixtures.append(('rawtrap', '_=terminal(#cast(i64,cpacr()))', (102, b'unexpected trap', b'')))
    for fixture, body, expected in fixtures:
        project = work/fixture
        project.mkdir()
        check = 'if cpacr() & 0x00f00000 != 0 { #panic("FPU") } ' if audit and target.startswith('thumb') else ''
        (project/'main.dyn').write_text(SOURCE+'fn main() { '+check+body+' '+check+'}\n')
        for mode in ('ssa', 'tree'):
            image = work/f'{fixture}-{mode}.elf'
            result = subprocess.run([compiler, 'build', str(project), '--release', '--target', target,
                '--no-cache', '--opt-remarks', '--output', str(image), '--link', str(obj)],
                env=environment(mode, adapter), capture_output=True, text=True, timeout=120)
            assert result.returncode == 0, result.stdout+result.stderr
            remarks(result.stdout+result.stderr, mode)
            if audit:
                audit['check_image'](image)
            actual = run_guest([*qemu, *board, '-nographic', '-kernel', str(image)])
            assert actual == expected, (target, adapter, fixture, mode, expected, actual)
            print(f'PASS {target} {"backend-adapter" if adapter else "production"} {fixture} {mode}: {actual}', flush=True)
    return len(fixtures)*2


def main():
    controls()
    for label, command in [('DYN', [DYN]), ('CLANG', CLANG)]:
        if not command or not shutil.which(command[0]):
            print(f'SKIP cases: {label} unavailable: {command}', flush=True)
            return
    production = backend = negatives = 0
    with tempfile.TemporaryDirectory(prefix='dyn-ssa-cases-') as temporary:
        work = Path(temporary)
        adapter = build_adapter(work)
        for target, variable, program, flags, board in b.TARGETS:
            qemu = shlex.split(os.environ.get(variable, '')) or [program]
            if not shutil.which(qemu[0]):
                print(f'SKIP {target} hard/soft guests: unavailable {qemu}; set {variable}', flush=True)
                continue
            for issoft in (False, True):
                t = target + ('-soft' if issoft else '')
                rv = t.startswith('riscv')
                ff = flags
                if issoft:
                    ff = ([f.replace('rv32imafd', 'rv32im').replace('ilp32d', 'ilp32') for f in flags]
                          if rv else ['--target=arm-none-eabi', '-mcpu=cortex-m7', '-mthumb', '-mfloat-abi=soft'])
                bb = [*board, *(['-cpu', 'sifive-e31'] if issoft and rv else [])]
                audit = soft.fixture('rv32' if rv else 'thumb')[0] if issoft else None
                target_work = work/t
                target_work.mkdir()
                frontend_negatives(target_work, t)
                negatives += 4
                production += guests(target_work/'production', DYN, t, ff, bb, qemu, False, audit)
                if adapter:
                    backend += guests(target_work/'backend', adapter, t, ff, bb, qemu, True, audit)
    print(f'{"PASS" if production else "SKIP"} cases: {production}/24 production guests; '
          f'{backend}/32 backend-only guests; {negatives}/16 frontend rejection checks; '
          '9 named SSA functions per SSA image; every soft image audited for FP', flush=True)


if __name__ == '__main__':
    main()
