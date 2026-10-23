#!/usr/bin/env python3
"""Production direct packed calls: 83 named functions, eight guests, 40 rejections.

ROOT/DYN/CLANG and DYN_QEMU_ARM/RISCV32 override portable tool locations.
TMPDIR controls cleaned temporary fixtures; container wrappers must mount it at
its identical host path and bound their own guest lifetime. No frontend bypass.
The separate internal sanitized preflight harness is not part of this suite.
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

src='use "std/io"\nstruct Big { a:u64,b:u64,c:u64,d:u64,e:u64 }\n'
names=[];checks=[]
def fn(n,pars,ret,body):
 global src
 src+=f'pub fn {n}({pars}) {ret} {{ {body} }}\n';names.append(n)
for n,t,expr,v in [('ints','u32','x[0]+x[1]','11,22'),('floats','f64','#cast(u32,x[0]+x[1])','11.0,22.0'),('texts','[]const u8','#cast(u32,#len(x[0])+#len(x[1]))','"hello","world!"'),('aggs','Big','#cast(u32,x[0].a+x[1].e)','Big{a:11},Big{e:22}')]:
 fn(n,f'x:...{t}','u32',f'if #len(x)==0 {{ return 0 }} return {expr}')
 fn(n+'call','','u32',f'return {n}()+{n}({v})'); checks.append(f'{n}call()!={11 if n=="texts" else 33}')
fn('bigpack','x:...u32','Big','if #len(x)==0 { return Big{a:7} } return Big{a:#cast(u64,x[0]),e:#cast(u64,#len(x))}')
fn('bigcall','','u32','a:=bigpack() b:=bigpack(11,22) return #cast(u32,a.a+b.a+b.e)');checks.append('bigcall()!=20')
for n in range(12):
 for t,val in [('u32','1'),('f64','1.0')]:
  name=f'bank{n}{t}';pars=','.join(f'a{i}:{t}' for i in range(n));args=','.join([val]*n)
  fn(name,(pars+',' if n else '')+'x:...u32','u32',('return #cast(u32,a0)+' if n else 'return ')+'#cast(u32,#len(x))')
  fn(name+'call','','u32',f'return {name}({args+"," if n else ""}11,22)');checks.append(name+f'call()!={3 if n else 2}')
src+='g:Big\nseq:u32\n'
fn('step','n:u32','u32','seq=seq*10+n return n')
fn('change','','Big','g.a=99 return g')
fn('snap','fixed:u32,x:...Big','u32','return fixed+#cast(u32,x[0].a+x[1].a)')
fn('snapcall','','u32','g=Big{a:11} return snap(step(1),g,change())');checks.append('snapcall()!=111')
fn('order','fixed:u32,x:...u32','u32','return fixed+x[0]+x[1]')
fn('ordercall','','u32','seq=0 _=order(step(1),step(2),step(3)) return seq');checks.append('ordercall()!=123')
fn('recurse','n:u32,x:...u32','u32','if n==0 { return x[0] } return recurse(n-1,x[0]+1)')
fn('recursecall','','u32','return recurse(5,7)');checks.append('recursecall()!=12')
fn('callback','p:fn(u32) u32,x:...u32','u32','return p(x[0])')
fn('plus','x:u32','u32','return x+1')
fn('callbackcall','','u32','return callback(&plus,41)');checks.append('callbackcall()!=42')
fn('manyextras','x:...u32','u32','return #cast(u32,#len(x))+x[511]')
fn('extrascall','','u32','return manyextras('+','.join(['1']*512)+')');checks.append('extrascall()!=513')
for n,ret in [(510,'u32'),(509,'Big')]:
 name=f'cap{n}';pars=','.join(f'a{i}:u32' for i in range(n));args=','.join(['1']*n)
 fn(name,pars+',x:...u32',ret,'return '+('a0+a'+str(n-1)+'+#cast(u32,#len(x))' if ret=='u32' else 'Big{a:#cast(u64,a0+a508)+#cast(u64,#len(x))}'))
 fn(name+'call','', 'u32', f'return '+(f'{name}({args})' if ret=='u32' else f'#cast(u32,{name}({args}).a)'));checks.append(name+'call()!=2')
src+='descstate:[]const u8\n'
fn('descchange','','[]const u8','descstate="longer" return descstate')
fn('descsnap','x:...[]const u8','u32','return #cast(u32,#len(x[0])*10+#len(x[1]))')
fn('descsnapcall','','u32','descstate="old" return descsnap(descstate,descchange())');checks.append('descsnapcall()!=36')
fn('nestedcall','','u32','return ints(ints(1,2),ints(3,4))');checks.append('nestedcall()!=10')
for n,ret in [(510,'u32'),(509,'Big')]:
 name=f'cap{n}fullcall';args=','.join(['1']*n+['7'])
 fn(name,'','u32',f'return '+(f'cap{n}({args})' if ret=='u32' else f'#cast(u32,cap{n}({args}).a)'));checks.append(name+'()!=3')
src+='extern fn inspect(p:rawptr,n:usize) u32\n'
fn('anypack','x:...any','u32','return inspect(#cast(rawptr,&x[0]),#len(x))')
fn('anycall','x:any','u32','return anypack(#cast(i32,17),#cast(f64,3.5),"ok",x)');
# Caller supplies an actual any; the packed fourth entry must box its descriptor.
src+='extern fn anyoracle() u32\n'
checks.append('anyoracle()!=0')
src+='pub fn anydebug() { _=io.println(io.stdout(),"any={}",anyoracle()) }\n'
c='''typedef unsigned W; typedef unsigned long long U;
extern W anycall(U,W);
W inspect(W p,W n) { if(n!=4 || (p&7))return 1; unsigned char *a=(void*)p;
U t0=*(U*)(a),t1=*(U*)(a+16),t2=*(U*)(a+32),t3=*(U*)(a+48);
W p0=*(W*)(a+8),p1=*(W*)(a+24),p2=*(W*)(a+40),p3=*(W*)(a+56);
if(t0!=6||t1!=15||t3!=18||t2==t3)return 2;
if(*(int*)p0!=17||*(U*)p1!=0x400c000000000000ULL)return 3;
W *s=(W*)p2;if(s[1]!=2||*(char*)s[0]!='o')return 4;
if(*(U*)p3!=0x1122334455667788ULL||**(W**)(p3+8)!=91)return 5;
return 0; }
W anyoracle(void) { W x=91; return anycall(0x1122334455667788ULL,(W)&x); }
W cpacr(void){return *(volatile W*)0xe000ed88u;}
'''
src+='fn main() { anydebug() '+''.join(f'if {x} {{ #panic("case{i}") }} ' for i,x in enumerate(checks))+'_ = io.write_all(io.stdout(),"PACK OK\\n") }\n'

cases={
'anyreturn':'pub fn bad(x:any) any { return x }\nfn main() {}',
'pointer':'fn packed(x:...u32) u32 { return #cast(u32,#len(x)) }\nfn main() { p:=&packed _=p(1) }',
'generic':'fn packed(x:...$T) u32 { return #cast(u32,#len(x)) }\nfn main() { _=packed(1) }',
'groups512':'pub fn packed('+','.join(f'a{i}:u32' for i in range(512))+',x:...u32) u32 { return #cast(u32,#len(x)) }\nfn main() { _=packed('+','.join(['1']*512)+') }',
'extras513':'pub fn packed(x:...u32) u32 { return #cast(u32,#len(x)) }\nfn main() { _=packed('+','.join(['1']*513)+') }'
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
        for name, source in cases.items():
            project = base/(target+'-'+name)
            project.mkdir()
            (project/'main.dyn').write_text(source)
            for mode in ('ssa', 'tree'):
                result = subprocess.run([DYN, 'build', str(project), '--target', target,
                    '--release', '--no-cache', '--opt-remarks', '--output', str(project/(mode+'.elf'))],
                    capture_output=True, text=True, env=environment(mode), timeout=120)
                log = result.stdout + result.stderr
                expected = {'anyreturn': 'returning any would escape borrowed storage',
                    'pointer': 'native variadic function pointers are not supported',
                    'generic': 'generic functions cannot be variadic'}.get(name, 'native emission failed')
                assert result.returncode != 0 and expected in log, (target, name, mode, log)
                completed += 1
    assert completed == 40
    print('PASS packed: 40/40 production rejection checks', flush=True)


def main():
    assert len(names) == len(set(names)) == 83, names
    soft.controls(names)
    # Also ensure fallback messages cannot coexist with claimed SSA selection.
    lines = '\n'.join(f'remark: {n}: SSA code generation, control' for n in names)
    for name in names:
        try:
            soft.remarks(lines + f'\nremark: {name}: tree emitter fallback', 'ssa', names)
        except AssertionError:
            continue
        raise AssertionError(('fallback remark accepted', name))
    print('PASS packed: 83 missing-remark, 83 fallback-remark and tree-mode negative controls', flush=True)
    if not shutil.which(DYN):
        print(f'SKIP packed: DYN executable unavailable: {DYN}', flush=True)
        return
    with tempfile.TemporaryDirectory(prefix='dyn-ssa-packed-') as temporary:
        base = Path(temporary)
        rejections(base)
        if not CLANG or not shutil.which(CLANG[0]):
            print(f'SKIP packed: Clang unavailable: {CLANG}; 0/8 guests', flush=True)
            return
        completed = 0
        for target, variable, program, flags, board in b.TARGETS:
            qemu = shlex.split(os.environ.get(variable, '')) or [program]
            if not shutil.which(qemu[0]):
                print(f'SKIP packed {target} hard/soft: {qemu[0]} unavailable; set {variable}', flush=True)
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
                        source = 'extern fn cpacr() u32\n' + source.replace('fn main() {',
                            'fn main() { if cpacr() & 0x00f00000 != 0 { #panic("FPU") }').replace(
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
                    if sf:
                        fixture, _ = soft.fixture('rv32' if rv else 'thumb')
                        print('PASS no-FP audit:', label, mode, fixture['check_image'](image), flush=True)
                    actual = run_guest([*qemu, *bd, '-nographic', '-kernel', str(image)])
                    assert actual == (0, b'any=0\nPACK OK\n', b''), (label, mode, actual)
                    completed += 1
                    print('PASS packed:', label, mode, '83 named functions; exact any=0/PACK OK', flush=True)
        print(f'{"PASS" if completed else "SKIP"} packed: {completed}/8 guests; 40/40 rejections', flush=True)


if __name__ == '__main__':
    main()
