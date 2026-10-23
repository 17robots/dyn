#!/usr/bin/env python3
"""Foreign C varargs: 140 named functions, eight guests, 64 rejections.

ROOT/DYN/CLANG and DYN_QEMU_ARM/RISCV32 override portable tool locations.
TMPDIR controls cleaned temporary fixtures; container wrappers must mount it at
its identical host path and bound their own guest lifetime. No frontend bypass.
Real Clang va_list consumers independently check the C ABI. Optional
LLVM_OBJDUMP checks actual indirect instructions. The retained internal
sanitized preflight harness is temporary evidence, not part of this suite.
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

R = Path(os.environ.get('ROOT', Path(__file__).resolve().parents[1])).resolve()
DYN = str(Path(os.environ.get('DYN', R/'build/dyn-release')).resolve())
CLANG = shlex.split(os.environ.get('CLANG', 'clang'))

def mod(name):
    spec = importlib.util.spec_from_file_location(name, R/'tests'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

b = mod('bare-ssa')
soft = mod('bare-ssa-soft')

OBJDUMP = shlex.split(os.environ.get('LLVM_OBJDUMP', 'llvm-objdump'))
src='use "std/io"\n';c='#include <stdarg.h>\ntypedef unsigned W; typedef unsigned long long U;\nW cpacr(void){\n#ifdef __arm__\nreturn *(volatile W*)0xe000ed88;\n#else\nreturn 0;\n#endif\n}\nU bits(double x){union{double f;U u;}v={x};return v.u;}\nW bitsf(float x){union{float f;W u;}v={x};return v.u;}\n'
names=[];checks=[]
def fn(n,p,t,body):
 global src
 src+=f'pub fn {n}({p}) {t} {{ {body} }}\n';names.append(n)
# Every GP boundary and FP exhaustion, promoted f32 and narrow ints, named FP.
for typ,ct,val,check in [('u32','W','7','a{i}!=7'),('f64','double','3.5','bits(a{i})!=0x400c000000000000ULL')]:
 for n in range(1,12):
  name=f'bank{n}{typ}';pars=','.join(f'a{i}:{typ}' for i in range(n));cp=','.join(f'{ct} a{i}' for i in range(n));args=','.join([val]*n)
  src+=f'extern fn c{name}({pars},...) u32\n'
  fn(name,'','u32',f'return c{name}({args},#cast(f32,1.5),#cast(i8,-7),(#cast(u64,0x11223344)<<32|#cast(u64,0x55667788)),19)')
  c+=f'W c{name}({cp},...){{va_list ap;va_start(ap,a{n-1});W bad='+ '||'.join(check.format(i=i) for i in range(n))+';bad|=bits(va_arg(ap,double))!=0x3ff8000000000000ULL;bad|=va_arg(ap,int)!=-7;bad|=va_arg(ap,U)!=0x1122334455667788ULL;bad|=va_arg(ap,int)!=19;va_end(ap);return bad;}\n'
  checks.append(f'{name}()!=0')
# Aggregate named argument snapshots, scalar and all return banks.
cts={'u8':'unsigned char','u32':'W','u64':'U','f32':'float','f64':'double'}
for name,fields in [('Byte',[('a','u8')]),('Odd',[(x,'u8') for x in 'abc']),('Core',[('a','u32'),('b','u32')]),('Mixed',[('a','f64'),('b','u32')]),('Large',[(x,'u64') for x in 'abcde'])]+[(f'H{n}',[(chr(97+i),'f32') for i in range(n)]) for n in range(1,5)]+[(f'D{n}',[(chr(97+i),'f64') for i in range(n)]) for n in range(1,5)]:
 src+=f'struct {name} {{'+','.join(f'{f}:{t}' for f,t in fields)+'}\n'
 c+='typedef struct{'+''.join(f'{cts[t]} {f};' for f,t in fields)+f'}}{name};\n'
 src+=f'extern fn c{name}(x:{name},...) {name}\n'
 fn('ret'+name,f'x:{name}',name,f'return c{name}(x,#cast(f32,1.5),17)')
 c+=f'{name} c{name}({name} x,...){{va_list ap;va_start(ap,x);if(bits(va_arg(ap,double))!=0x3ff8000000000000ULL||va_arg(ap,int)!=17)x.a=0;va_end(ap);return x;}}\n'
 vals=','.join(f'{f}:#cast({t},3.0)' if t.startswith('f') else f'{f}:3' for f,t in fields)
 fn('test'+name,'','u32',f'x:=ret{name}({name}{{{vals}}}) return '+ '+'.join(f'#cast(u32,x.{f})' for f,t in fields))
 checks.append(f'test{name}()!={3*len(fields)}')
 for n in [3,7,9]:
  for scalar,ct,value in [('u32','W','7'),('f64','double','3.5')]:
   bank=f'agg{n}{name}{scalar}';pars=','.join(f'a{i}:{scalar}' for i in range(n));cp=','.join(f'{ct} a{i}' for i in range(n));args=','.join([value]*n)
   src+=f'extern fn c{bank}({pars},x:{name},...) {name}\n'
   fn(bank,'','u32',f'x:=c{bank}({args},{name}{{{vals}}},#cast(f32,1.5),17) return '+ '+'.join(f'#cast(u32,x.{f})' for f,t in fields))
   named='||'.join((f'a{i}!=7' if scalar=='u32' else f'bits(a{i})!=0x400c000000000000ULL') for i in range(n))
   c+=f'{name} c{bank}({cp},{name} x,...){{va_list ap;va_start(ap,x);if({named}||bits(va_arg(ap,double))!=0x3ff8000000000000ULL||va_arg(ap,int)!=17)x.a=0;va_end(ap);return x;}}\n'
   checks.append(f'{bank}()!={3*len(fields)}')
for typ,ct,val,bits in [('f32','float','1.5','0x3fc00000'),('f64','double','3.5','0x400c000000000000ULL')]:
 src+=f'extern fn c{typ}(x:u32,...) {typ}\n'
 fn('ret'+typ,'',typ,f'return c{typ}(1,#cast(f32,1.5))')
 c+=f'{ct} c{typ}(W x,...){{va_list ap;va_start(ap,x);U u=bits(va_arg(ap,double));va_end(ap);return u==0x3ff8000000000000ULL ? {val}:0;}}\n'
 checks.append(f'ret{typ}()!={val}')
src+='extern fn cv(x:u32,...) u32\nextern fn choose() u32\n'
fn('indirect','','u32','p:=&cv if choose()!=0 { p=&cvother } return p(1,#cast(f32,1.5),23)')
src+='extern fn cvother(x:u32,...) u32\n'
c+='W choose(void){return 0;} W cv(W x,...){va_list ap;va_start(ap,x);W ok=bits(va_arg(ap,double))==0x3ff8000000000000ULL && va_arg(ap,int)==23;va_end(ap);return ok?77:0;} W cvother(W x,...){return 99;}\n'
checks.append('indirect()!=77')
fn('callback','x:f64','f64','return x')
src+='extern fn cb(p:*fn(f64) f64,...) f64\n'
fn('reentry','','f64','return cb(&callback,#cast(f32,1.5))')
c+='double cb(double(*p)(double),...){va_list ap;va_start(ap,p);double x=va_arg(ap,double);va_end(ap);return p(x);}\n'
checks.append('reentry()!=1.5')
fn('nestedarg','','u32','return cv(1,callback(1.5),23)')
checks.append('nestedarg()!=77')
src+='seq:u32\n'
fn('step','n:u32','u32','seq=seq*10+n return n')
src+='extern fn order(x:u32,...) u32\n'
fn('ordering','','u32','seq=0 _=order(step(1),step(2),step(3)) return seq')
c+='W order(W x,...){va_list ap;va_start(ap,x);W a=va_arg(ap,W),b=va_arg(ap,W);va_end(ap);return x+a+b;}\n';checks.append('ordering()!=123')
src+='state:Large\nextern fn snap(x:Large,...) u32\n'
fn('change','','u32','state.a=99 return 7')
fn('snapshot','','u32','state=Large{a:11,e:55} return snap(state,change())')
c+='W snap(Large x,...){va_list ap;va_start(ap,x);W a=va_arg(ap,int);va_end(ap);return x.a==11 && x.e==55 && a==7?88:0;}\n';checks.append('snapshot()!=88')
src+='extern fn touch(p:rawptr)\n';c+='void touch(void*p){__asm__ volatile(""::"r"(p):"memory");}\n'
fn('largeframe','','u32','a:[2049]u64=[] touch(&a) return cv(1,#cast(f32,1.5),23)');checks.append('largeframe()!=77')
src+='extern fn capacity(x:u32,...) u32\n'
fn('capacitycall','','u32','return capacity(511,'+','.join(['1']*511)+')')
c+='W capacity(W x,...){va_list ap;va_start(ap,x);W sum=0;for(W i=0;i<x;i++)sum+=va_arg(ap,int);va_end(ap);return sum;}\n';checks.append('capacitycall()!=511')
src+='extern fn capret(n:u32,...) Large\n'
fn('capsret','','u32','x:=capret(510,'+','.join(['1']*510)+') return #cast(u32,x.a)')
fn('capsretindirect','','u32','p:=&capret x:=p(510,'+','.join(['1']*510)+') return #cast(u32,x.a)')
c+='Large capret(W n,...){va_list ap;va_start(ap,n);W sum=0;for(W i=0;i<n;i++)sum+=va_arg(ap,int);va_end(ap);Large r={sum,2,3,4,5};return r;}\n'
checks+=['capsret()!=510','capsretindirect()!=510']
src+='extern fn cpacr() u32\nfn main(){'+''.join(f'if {ch} {{ #panic("case {i}") }}' for i,ch in enumerate(checks))+'_ = io.write_all(io.stdout(),"VARARGS OK\\n") }\n'

cases={
'bool':'x:=true', 'rawptr':'x:=#cast(rawptr,0)', 'array':'x:[2]u32=[1,2]',
'aggregate':'x:=S{a:1}', 'string':'x:="abc"', 'slice':'a:[2]u32=[1,2] x:=a[0..2]',
'pointer':'p:=&packed _=p(1)', 'any':'',
}

def run_guest(command):
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=10)
        raise AssertionError(f'guest exceeded 30 seconds: {command}')
    return process.returncode, stdout.replace(b'\r\n', b'\n'), stderr


def environment(mode):
    env = dict(os.environ)
    env.pop('DYN_NO_SSA', None)
    if mode == 'tree':
        env['DYN_NO_SSA'] = '1'
    return env


def rejections(base):
    completed = 0
    for target in ('riscv32-none', 'riscv32-none-soft', 'thumbv7em-none', 'thumbv7em-none-soft'):
        for name, body in cases.items():
            work = base/(target+'-'+name)
            work.mkdir()
            source = 'struct S { a:u32 }\nextern fn cv(n:u32,...) u32\nfn packed(x:...u32) u32 { return 0 }\nfn main(){'+body+(' _=cv(1,x)' if name!='pointer' else '')+'}\n'
            if name == 'any':
                source = 'extern fn cv(n:u32,...) u32\npub fn rejected(x:any){_=cv(1,x)}\nfn main(){}\n'
            (work/'main.dyn').write_text(source)
            for mode in ('ssa', 'tree'):
                result = subprocess.run([DYN, 'build', str(work), '--release', '--target', target,
                    '--no-cache', '--output', str(work/(mode+'.elf'))], env=environment(mode),
                    capture_output=True, text=True, timeout=120)
                expected = ('native variadic function pointers are not supported' if name == 'pointer'
                            else 'C variadic argument requires integer, float, or pointer')
                log = result.stdout + result.stderr
                assert result.returncode != 0 and expected in log, (target, name, mode, log)
                completed += 1
    assert completed == 64
    print('PASS varargs: 64/64 production frontend rejections', flush=True)


def check_indirect(image, rv):
    # Restrict the decoder to the opaque choose()-selected call's function.
    # RV direct calls use jal or an auipc/jalr pair through ra; exclude ra.
    result = subprocess.run([*OBJDUMP, *([] if rv else ['--mcpu=cortex-m7']),
                             '--disassemble-symbols=indirect', str(image)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert '<indirect>:' in result.stdout, result.stdout
    pattern = r'\bjalr\s+(?:t[0-6]|a[0-7]|s(?:[0-9]|1[01]))\s*$' if rv else r'\bblx\s+r(?:[0-9]|1[0-2])\s*$'
    assert re.search(pattern, result.stdout, re.M), result.stdout


def main():
    assert len(names) == len(set(names)) == 140, names
    soft.controls(names)
    # Also ensure fallback messages cannot coexist with claimed SSA selection.
    lines = '\n'.join(f'remark: {n}: SSA code generation, control' for n in names)
    for name in names:
        try:
            soft.remarks(lines + f'\nremark: {name}: tree emitter fallback', 'ssa', names)
        except AssertionError:
            continue
        raise AssertionError(('fallback remark accepted', name))
    print('PASS varargs: 140 missing-remark, 140 fallback-remark and tree-mode negative controls', flush=True)
    if not shutil.which(DYN):
        print(f'SKIP varargs: DYN executable unavailable: {DYN}', flush=True)
        return
    with tempfile.TemporaryDirectory(prefix='dyn-ssa-varargs-') as temporary:
        base = Path(temporary)
        rejections(base)
        if not CLANG or not shutil.which(CLANG[0]):
            print(f'SKIP varargs: Clang unavailable: {CLANG}; 0/8 guests', flush=True)
            return
        decoder = bool(OBJDUMP and shutil.which(OBJDUMP[0]))
        if not decoder:
            print('SKIP varargs indirect-instruction assertion: LLVM_OBJDUMP unavailable', flush=True)
        indirect_checks = 0
        completed = 0
        for target, variable, program, flags, board in b.TARGETS:
            qemu = shlex.split(os.environ.get(variable, '')) or [program]
            if not shutil.which(qemu[0]):
                print(f'SKIP varargs {target} hard/soft: {qemu[0]} unavailable; set {variable}', flush=True)
                continue
            for sf in (False, True):
                label = target + ('-soft' if sf else '')
                work = base/label
                work.mkdir()
                project = work/'source'
                project.mkdir()
                rv = target.startswith('riscv')
                f, bd, source = flags, board, src
                if sf:
                    f = ([v.replace('rv32imafd', 'rv32im').replace('ilp32d', 'ilp32') for v in flags]
                         if rv else ['--target=arm-none-eabi', '-mcpu=cortex-m7', '-mthumb', '-mfloat-abi=soft'])
                    if rv:
                        bd = board + ['-cpu', 'sifive-e31']
                    else:
                        source = source.replace('fn main(){',
                            'fn main(){ if cpacr() & 0x00f00000 != 0 { #panic("FPU") }').replace(
                            '_ = io.write_all', 'if cpacr() & 0x00f00000 != 0 { #panic("FPU exit") } _ = io.write_all')
                (project/'main.dyn').write_text(source)
                (work/'oracle.c').write_text(c)
                obj = work/'oracle.o'
                subprocess.run([*CLANG, *f, '-ffreestanding', '-fno-stack-protector', '-O2',
                    '-c', str(work/'oracle.c'), '-o', str(obj)], check=True, timeout=60)
                if not rv:
                    b.arm_addends(obj)
                for mode in ('ssa', 'tree'):
                    image = work/(mode+'.elf')
                    result = subprocess.run([DYN, 'build', str(project), '--release', '--target', label,
                        '--no-cache', '--opt-remarks', '--link', str(obj), '--output', str(image)],
                        env=environment(mode), capture_output=True, text=True, timeout=120)
                    log = result.stdout + result.stderr
                    assert result.returncode == 0, (label, mode, log)
                    soft.remarks(log, mode, names)
                    if decoder:
                        check_indirect(image, rv)
                        indirect_checks += 1
                    if sf:
                        fixture, _ = soft.fixture('rv32' if rv else 'thumb')
                        print('PASS no-FP audit:', label, mode, fixture['check_image'](image), flush=True)
                    actual = run_guest([*qemu, *bd, '-nographic', '-kernel', str(image)])
                    assert actual == (0, b'VARARGS OK\n', b''), (label, mode, actual)
                    completed += 1
                    print('PASS varargs:', label, mode, '140 named functions; exact VARARGS OK', flush=True)
        print(f'{"PASS" if indirect_checks == 8 else "SKIP"} varargs: {indirect_checks}/8 indirect-instruction assertions', flush=True)
        print(f'{"PASS" if completed == 8 else "SKIP"} varargs: {completed}/8 guests; 64/64 rejections', flush=True)


if __name__ == '__main__':
    main()
