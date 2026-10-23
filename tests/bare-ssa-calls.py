#!/usr/bin/env python3
"""SSA32 scalar-call ABI oracle: 3 fixtures x 2 targets x 2 modes = 12 guests.

ROOT selects the compiler directory; DYN and CLANG override compilers.
DYN_QEMU_RISCV32 / DYN_QEMU_ARM are shell-split QEMU command prefixes.
Container wrappers must mount TMPDIR at the identical path and bound the
container guest (e.g. timeout 20 qemu-system-arm). Host process groups are
also killed on timeout. Generated fixtures use TemporaryDirectory/TMPDIR.
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
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
CLANG = shlex.split(os.environ.get('CLANG', 'clang'))
spec = importlib.util.spec_from_file_location('bare_ssa', ROOT/'tests/bare-ssa.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

src=r'''
use "std/io"
g:u64
cb:*fn(u64) u64
extern fn cwide(x:u64) u64
extern fn csplit(a:u32,b:u32,c:u32,d:u32,e:u32,f:u32,h:u32,x:u64,y:u32,z:u64) u64
extern fn cnarrow(a:i8,b:u16,c:i32) i64
extern fn cptr(p:rawptr) rawptr
extern fn ccallback() *fn(u64) u64
extern fn czero() u64
extern fn cvoid(x:u64)
extern fn oracle() i32
pub fn wide(x:u64) u64 { return cwide(x) }
pub fn directsplit(a:u32,b:u32,c:u32,d:u32,e:u32,f:u32,h:u32,x:u64,y:u32,z:u64) u64 { return csplit(a,b,c,d,e,f,h,x,y,z) }
pub fn indirectsplit(p:*fn(u32,u32,u32,u32,u32,u32,u32,u64,u32,u64) u64,x:u64,z:u64) u64 { return p(1,2,3,4,5,6,7,x,9,z) }
pub fn invoke(p:*fn(u64) u64,x:u64) u64 { return p(x) }
pub fn frommem(x:u64) u64 { return cb(x) }
pub fn fromresult(x:u64) u64 { return ccallback()(x) }
pub fn narrowcall(a:i8,b:u16,c:i32) i64 { return cnarrow(a,b,c) }
pub fn ptrcall(p:rawptr) rawptr { return cptr(p) }
pub fn zerocall() u64 { return czero() }
pub fn discarded(x:u64) { _=cwide(x) cvoid(x) }
pub fn mutate(x:u64) { g=x }
pub fn state(x:u64) u64 { g=x a:=g mutate(#wrap(x+1)) return #wrap(a+g) }
pub fn nested(x:u64,y:u64) u64 { a:=cwide(x) b:=cwide(cwide(y)) return #wrap(a+b+x+y) }
pub fn phicalls(x:u64,y:u64,n:u32) u64 { a:=x b:=y i:u32=0 for i<n { t:=cwide(a) a=b b=t i=#wrap(i+1) } return #wrap(a+b) }
pub fn checkedcall(x:u64) u64 { return cwide(x)+1 }
extern fn cfloat(x:f64) f64
struct Pair { a:u64,b:u64 }
extern fn cagg(x:Pair) Pair
pub fn deadfloat() { _=cfloat(1.0) }
pub fn deadagg() { _=cagg(Pair{a:1,b:2}) }
fn main() { cb=&cwide status:=oracle() if status!=0 { _=io.println(io.stdout(),"oracle {}",status) #panic("oracle") } _=io.write_all(io.stdout(),"CALLS OK\n") }
'''
c=r'''
typedef unsigned long long U; typedef unsigned W;
extern U wide(U), directsplit(W,W,W,W,W,W,W,U,W,U), indirectsplit(U(*)(W,W,W,W,W,W,W,U,W,U),U,U);
extern U invoke(U(*)(U),U), frommem(U), fromresult(U), zerocall(void), nested(U,U), phicalls(U,U,W), state(U);
extern long long narrowcall(signed char,unsigned short,int);
extern void *ptrcall(void*); extern void discarded(U);
U cwide(U x) { return x ^ 0x987654321abcdef0ULL; }
U csplit(W a,W b,W c,W d,W e,W f,W h,U x,W y,U z) { return a+2ULL*b+3ULL*c+4ULL*d+5ULL*e+6ULL*f+7ULL*h+8*x+9ULL*y+10*z; }
long long cnarrow(signed char a,unsigned short b,int c) { return (long long)a+b+c; }
void *cptr(void *p) { return p; }
U (*ccallback(void))(U) { return cwide; }
U czero(void) { return 0xfedcba9876543210ULL; }
volatile U saved;
void cvoid(U x) { saved=x; }
double cfloat(double x) { return x; }
struct Pair { U a,b; }; struct Pair cagg(struct Pair x) { return x; }
int oracle(void) {
 U x=0xf123456789abcdefULL,y=0x123456789abcdef0ULL;
 if(wide(x)!=cwide(x)) return 1;
 if(directsplit(1,2,3,4,5,6,7,x,9,y)!=csplit(1,2,3,4,5,6,7,x,9,y)) return 2;
 if(indirectsplit(csplit,x,y)!=csplit(1,2,3,4,5,6,7,x,9,y)) return 3;
 if(invoke(cwide,x)!=cwide(x)||frommem(x)!=cwide(x)||fromresult(x)!=cwide(x)) return 4;
 if(narrowcall(-123,65000,-2000000000)!=cnarrow(-123,65000,-2000000000)) return 5;
 if(ptrcall((void*)0xfedcba98)!=(void*)0xfedcba98) return 6;
 if(zerocall()!=czero()) return 7;
 discarded(x); if(saved!=x) return 8;
 if(state(x)!=x+x+1) return 9;
 if(nested(x,y)!=cwide(x)+cwide(cwide(y))+x+y) return 10;
 for(W n=0;n<9;n++) { U a=x,b=y;for(W i=0;i<n;i++){U t=cwide(a);a=b;b=t;} if(phicalls(x,y,n)!=a+b) return 11; }
 return 0;
}
'''
src += r"""
extern fn cnovoid()
pub fn indirectvoid(p:*fn()) { p() }
pub fn directvoid() { cnovoid() }
extern fn cmix(a:u32,b:u64,c:u32,d:u64,e:u32,f:u64) u64
pub fn mixcall(a:u32,b:u64,c:u32,d:u64,e:u32,f:u64) u64 { return cmix(a,b,c,d,e,f) }
extern fn ci8(x:i8) i8
extern fn cu16(x:u16) u16
extern fn cisize(x:isize) isize
pub fn ret_i8(x:i8) i64 { return #cast(i64,ci8(x)) }
pub fn ret_u16(x:u16) u64 { return #cast(u64,cu16(x)) }
pub fn ret_isize(x:isize) i64 { return #cast(i64,cisize(x)) }
pub fn castfn(p:rawptr,x:u64) u64 { return #cast(*fn(u64) u64,p)(x) }
extern fn cfarg(x:f64) u32
extern fn cfret() f64
fn cdesc(x:[]const u8) u32 { return #cast(u32,#len(x)) }
pub fn deadfarg() { _=cfarg(1.0) }
pub fn deadfret() { _=cfret() }
pub fn deaddesc() { _=cdesc("") }
pub fn unreachablefp(x:u64) { if x!=x { _=cfarg(1.0) } }
extern fn cvar(x:i32, ...) i32
pub fn deadvariadic() { _=cvar(1,2) }
pub fn protectedcall(x:u64) u64 { defer { g=0 } return cwide(x) }
"""
c += r"""
void cnovoid(void) { saved=123; }
extern void indirectvoid(void(*)(void)), directvoid(void);
U cmix(W a,U b,W c,U d,W e,U f) { return a+2*b+3*c+4*d+5*e+6*f; }
signed char ci8(signed char x) { return x; }
unsigned short cu16(unsigned short x) { return x; }
int cisize(int x) { return x; }
int cvar(int x, ...) { return x; }
W cfarg(double x) { return x; } double cfret(void) { return 1; }
W cdesc(void *p,W n) { return n; }
extern U mixcall(W,U,W,U,W,U), ret_u16(unsigned short), castfn(void*,U);
extern long long ret_i8(signed char), ret_isize(int);
int extra(void) {
 saved=0; indirectvoid(cnovoid); if(saved!=123) return 4; saved=0;directvoid();if(saved!=123) return 5;
 if(mixcall(1,0xfedcba9876543210ULL,3,0x123456789abcdef0ULL,5,0xabcdef1234567890ULL)!=cmix(1,0xfedcba9876543210ULL,3,0x123456789abcdef0ULL,5,0xabcdef1234567890ULL)) return 1;
 if(ret_i8(-123)!=-123 || ret_u16(65000)!=65000 || ret_isize(-2000000000)!=-2000000000LL) return 2;
 if(castfn(cwide,0x123456789abcdef0ULL)!=cwide(0x123456789abcdef0ULL)) return 3;
 return 0;
}
"""
src += 'extern fn extra() i32\n'
src=src.replace('status:=oracle()', 'if extra()!=0 { #panic("extra") } status:=oracle()')
# 512 scalar operands plus indirect target: exceed the old operand buffer.
params=','.join(f'a{i}:u32' for i in range(512)); types=','.join(['u32']*512); args=','.join(str(i) for i in range(512))
src+=f'\npub fn manycallee({params}) u64 {{ return #cast(u64,a0)+#cast(u64,a511) }}\npub fn manycall(p:*fn({types}) u64) u64 {{ return p({args}) }}\n'
c+='\nextern U manycall(void*); extern U manycallee();\n'
# Include manycall from main; C oracle is kept straightforward.
src=src.replace('status:=oracle()', 'if manycall(&manycallee)!=511 { #panic("many") } status:=oracle()')
positive='protectedcall deadvariadic deadagg deaddesc deadfloat deadfarg deadfret unreachablefp wide directsplit indirectsplit invoke frommem fromresult narrowcall ptrcall zerocall discarded mutate state nested phicalls checkedcall manycallee manycall mixcall ret_i8 ret_u16 ret_isize castfn indirectvoid directvoid'.split()

FALLBACK = []


def check_remarks(log, mode):
    if mode == 'tree':
        assert 'SSA code generation' not in log, log
        return
    for name in positive + FALLBACK:
        messages = re.findall(r'^remark: ' + re.escape(name) + r': (.*)$', log, re.M)
        expected = 'SSA code generation,' if name in positive else 'tree emitter (paired SSA boundary)'
        forbidden = 'tree emitter' if name in positive else 'SSA code generation'
        assert any(message.startswith(expected) for message in messages), (name, expected, log)
        assert not any(forbidden in message for message in messages), (name, messages)


def run_guest(command):
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise AssertionError(f'guest exceeded 30 seconds: {command}')
    return process.returncode, stdout.replace(b'\r\n', b'\n'), stderr


def main():
    # Exercise the actual checker: correct guest output cannot replace SSA proof.
    for name in positive + FALLBACK:
        log = '\n'.join('remark: ' + other + ': ' +
            ('SSA code generation, test' if other in positive else 'tree emitter (paired SSA boundary)')
            for other in positive + FALLBACK if other != name)
        try:
            check_remarks(log, 'ssa')
        except AssertionError:
            pass
        else:
            raise AssertionError(f'missing named lowering remark accepted: {name}')
    for label, command in [('DYN', [DYN]), ('CLANG', CLANG)]:
        if not command or not shutil.which(command[0]):
            print(f'SKIP scalar calls: {label} executable unavailable: {command}', flush=True)
            return
    completed = 0
    for target, variable, program, flags, board in b.TARGETS:
        qemu = shlex.split(os.environ.get(variable, '')) or [program]
        if not shutil.which(qemu[0]):
            print(f'SKIP {target}: {qemu[0]} unavailable; set {variable}', flush=True)
            continue
        with tempfile.TemporaryDirectory(prefix='dyn-ssa-calls-') as temporary:
            work = Path(temporary)
            project = work/'source'
            project.mkdir()
            (work/'oracle.c').write_text(c)
            obj = work/'oracle.o'
            subprocess.run([*CLANG, *flags, '-ffreestanding', '-fno-stack-protector',
                '-O2', '-c', str(work/'oracle.c'), '-o', str(obj)], check=True, timeout=60)
            if target == 'thumbv7em-none':
                b.arm_addends(obj)
            cases = [
                ('success', src, (0, b'CALLS OK\n', b'')),
                ('null', src.replace('cb=&cwide', 'cb=&cwide _=invoke(nil,1)'),
                 (101, b'runtime check failed (function.nonnull.ok) in invoke\n', b'')),
                ('overflow', src.replace('cb=&cwide', 'cb=&cwide _=checkedcall(0x6789abcde543210f)'),
                 (101, b'runtime check failed (overflow.ok) in checkedcall\n', b'')),
            ]
            for name, source, expected in cases:
                (project/'main.dyn').write_text(source)
                for mode in ('ssa', 'tree'):
                    env = dict(os.environ)
                    env.pop('DYN_NO_SSA', None)
                    if mode == 'tree':
                        env['DYN_NO_SSA'] = '1'
                    image = work/f'{name}-{mode}.elf'
                    build = subprocess.run([DYN, 'build', str(project), '--release', '--target', target,
                        '--no-cache', '--opt-remarks', '--link', str(obj), '--output', str(image)],
                        env=env, capture_output=True, text=True, timeout=120)
                    log = build.stdout + build.stderr
                    assert build.returncode == 0, (target, name, mode, log)
                    check_remarks(log, mode)
                    actual = run_guest([*qemu, *board, '-nographic', '-kernel', str(image)])
                    assert actual == expected, (target, name, mode, expected, actual)
                    completed += 1
                print(f'PASS {target} {name}: SSA/tree expected status/output; named lowering', flush=True)
    if completed:
        print(f'PASS scalar calls: {completed}/12 guests; {len(positive)} named SSA, '
              f'{len(FALLBACK)} fallbacks; missing-remark negative controls', flush=True)
    else:
        print('SKIP scalar calls: no QEMU targets executed', flush=True)


if __name__ == '__main__':
    main()
