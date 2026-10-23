#!/usr/bin/env python3
"""Aggregate callable ABI: 164 named functions, RV32/Thumb, SSA/tree.

The independent Clang oracle exercises ordinary C structs in both directions.
Raw Dyn arrays use explicit scalar-word/sret ABI adapters, not C structs.
Covers tails, mixed banks, HFA1-4, bank exhaustion/splits, immediate by-value
snapshots, nested sret, an 8,200-byte frame, and 511 arguments+sret+target.

ROOT selects the compiler directory; DYN and CLANG override compilers.
DYN_QEMU_RISCV32 / DYN_QEMU_ARM are shell-split command prefixes. Container
wrappers must mount TMPDIR at the same path and bound their guest process.
TemporaryDirectory respects TMPDIR and removes fixtures even on failure.
Missing executables explicitly SKIP; compilation/execution failures fail.
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

source='use "std/io"\n'
c='typedef unsigned W;\n'
names=[];checks=[]
for name,fields,values in [('Byte',[('a','u8')],[19]),('Odd',[('a','u8'),('b','u8'),('c','u8')],[19,23,27]),('Seven',[(x,'u8') for x in 'abcdefg'],list(range(11,18))),('Mixed',[('a','f64'),('b','u32')],[3.5,27]),('MixRev',[('a','u32'),('b','f32')],[27,3.5]),('Large',[(x,'u64') for x in 'abcde'],[11,22,33,44,55])]+[(f'H{n}',[(chr(97+i),'f32') for i in range(n)],[i+1.5 for i in range(n)]) for n in range(1,5)]+[(f'D{n}',[(chr(97+i),'f64') for i in range(n)],[i+1.5 for i in range(n)]) for n in range(1,5)]:
 source+=f'struct {name} {{'+','.join(f'{f}:{t}' for f,t in fields)+'}\n'
 source+=f'extern fn c{name}(x:{name}) {name}\npub fn id{name}(x:{name}) {name} {{ return x }}\npub fn round{name}(x:{name}) {name} {{ return c{name}(c{name}(x)) }}\npub fn indirect{name}(p:*fn({name}) {name},x:{name}) {name} {{ return p(x) }}\n'
 names+=['id'+name,'round'+name,'indirect'+name]
 ct={'u8':'unsigned char','u32':'unsigned','u64':'unsigned long long','f32':'float','f64':'double'}
 c+=f'typedef struct {{'+''.join(f'{ct[t]} {f};' for f,t in fields)+f'}} {name};\n'
 c+=f'{name} c{name}({name} x) {{ x.{fields[0][0]}+=1; return x; }}\nextern {name} id{name}({name}),round{name}({name}),indirect{name}({name} (*)({name}),{name});\n'
 checks.append('{'+f'{name} x={{'+','.join(map(str,values))+f'}},a=id{name}(x),r=round{name}(x),q=indirect{name}(c{name},x);'+''.join(f'if(a.{f}!=x.{f} || r.{f}!=x.{f}+{2 if j==0 else 0} || q.{f}!=x.{f}+{1 if j==0 else 0}) return {len(checks)+1};' for j,(f,t) in enumerate(fields))+'}')

# Prefixes exhaust core/VFP banks; composites then split or move to stack.
for n in range(0,11):
 for typ in ['Seven','Mixed','Large','H4','D4']:
  for scalar,ct,val in [('u32','unsigned','7'),('f64','double','2.5')]:
   name=f'bank{n}{typ}{scalar}'
   pars=','.join(f'a{i}:{scalar}' for i in range(n));args=','.join(f'a{i}' for i in range(n));cp=','.join(f'{ct} a{i}' for i in range(n))
   if n:pars+=',';args+=',';cp+=','
   source+=f'extern fn c{name}({pars}x:{typ}) {typ}\npub fn {name}({pars}x:{typ}) {typ} {{ return c{name}({args}x) }}\n'
   names.append(name)
   c+=f'{typ} c{name}({cp}{typ} x) {{ x.a+=1; return x; }}\nextern {typ} {name}({cp}{typ});\n'
   checks.append('{'+f'{typ} x={{0}},r={name}('+','.join([val]*n+['x'])+');if(r.a!=1)return 100;}')
source+=r'''
state:Large
extern fn checkcopy(x:Large,y:u32) u32
pub fn changestate() u32 { state.a=999 return 3 }
pub fn isolation() u32 { state=Large{a:11,b:22,c:33,d:44,e:55} return checkcopy(state,changestate()) }
pub fn rawid(x:[3]u32) [3]u32 { return x }
pub fn rawsum(x:[3]u32) u32 { return x[0]+x[1]+x[2] }
pub fn rawnest(x:[3]u32) [3]u32 { return rawid(rawid(x)) }
pub fn rawtest() u32 { x:[3]u32=[11,22,33] y:=rawnest(x) return rawsum(y) }
'''
names+=['changestate','isolation','rawid','rawsum','rawnest','rawtest']
c+='extern unsigned isolation(void),rawtest(void);unsigned checkcopy(Large x,unsigned y){return x.a==11 && x.e==55 && y==3 ? 0:999;}\n'
checks+=['if(isolation()!=0)return 101;','if(rawtest()!=66)return 102;']
source+=r'''
extern fn craw_addr() rawptr
pub fn rawforeign(x:[3]u32) [3]u32 { return #cast(*fn([3]u32) [3]u32,craw_addr())(x) }
extern fn touch(p:rawptr)
pub fn bigframe(x:Mixed) Mixed { a:[1025]u64=[] touch(&a) return cMixed(x) }
pub fn partialmix(x:Mixed) u32 { return cMixed(x).b }
pub fn unusedmix(x:Mixed) { _=cMixed(x) }
'''
names+=['rawforeign','bigframe','partialmix','unusedmix']
c+='''
extern void rawid(W*,W,W,W),rawnest(W*,W,W,W),rawforeign(W*,W,W,W);
void craw(W *out,W a,W b,W c){out[0]=a+1;out[1]=b+2;out[2]=c+3;}
void *craw_addr(void){return (void*)craw;}
void touch(void *p){__asm__ volatile(""::"r"(p):"memory");}
extern Mixed bigframe(Mixed);extern W partialmix(Mixed);extern void unusedmix(Mixed);
'''
checks+=['{W a[3]={0};rawid(a,7,11,13);if(a[0]!=7||a[1]!=11||a[2]!=13)return 103;rawnest(a,17,19,23);if(a[0]!=17||a[1]!=19||a[2]!=23)return 104;rawforeign(a,27,31,37);if(a[0]!=28||a[1]!=33||a[2]!=40)return 105;}',
'{Mixed x={3.5,27},r=bigframe(x);if(r.a!=4.5||r.b!=27||partialmix(x)!=27)return 106;unusedmix(x);}']
# Maximum operand list includes hidden sret and the indirect target.
pars=','.join(f'a{i}:u32' for i in range(511));types=','.join(['u32']*511);args=','.join(str(i) for i in range(511))
source+=f'pub fn capacitycallee({pars}) Large {{ return Large{{a:#cast(u64,a0),b:#cast(u64,a510),c:3,d:4,e:5}} }}\npub fn capacitycall(p:*fn({types}) Large) u64 {{ return p({args}).b }}\n'
names+=['capacitycallee','capacitycall']
c+='extern unsigned long long capacitycall(void*);extern void capacitycallee(void);\n'
checks+=['if(capacitycall((void*)capacitycallee)!=510)return 107;']
source+='extern fn oracle() u32\nfn main() { n:=oracle() if n!=0 { _=io.println(io.stdout(),"BAD {}",n) #panic("oracle") } _=io.write_all(io.stdout(),"ABI OK\\n") }\n'
c+='unsigned oracle(void){'+''.join(checks)+'return 0;}\n'


def check_remarks(log, mode):
    if mode == 'tree':
        assert 'SSA code generation' not in log, log
        return
    for name in names:
        messages = re.findall(r'^remark: ' + re.escape(name) + r': (.*)$', log, re.M)
        assert any(message.startswith('SSA code generation,') for message in messages), (name, log)
        assert not any('tree emitter' in message for message in messages), (name, messages)


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
    assert len(names) == len(set(names)) == 164, names
    remarks = ['remark: ' + name + ': SSA code generation, test' for name in names]
    check_remarks('\n'.join(remarks), 'ssa')
    for index, name in enumerate(names):
        try:
            check_remarks('\n'.join(remarks[:index] + remarks[index + 1:]), 'ssa')
        except AssertionError:
            pass
        else:
            raise AssertionError(f'missing named SSA remark accepted: {name}')
    print('PASS aggregate-calls: 164 missing-remark negative controls', flush=True)
    for label, command in [('DYN', [DYN]), ('CLANG', CLANG)]:
        if not command or not shutil.which(command[0]):
            print(f'SKIP aggregate-calls: {label} executable unavailable: {command}', flush=True)
            return
    completed = 0
    for target, variable, program, flags, board in b.TARGETS:
        qemu = shlex.split(os.environ.get(variable, '')) or [program]
        if not shutil.which(qemu[0]):
            print(f'SKIP {target}: {qemu[0]} unavailable; set {variable}', flush=True)
            continue
        with tempfile.TemporaryDirectory(prefix='dyn-ssa-aggregate-calls-') as temporary:
            work = Path(temporary)
            project = work/'source'
            project.mkdir()
            (project/'main.dyn').write_text(source)
            (work/'oracle.c').write_text(c)
            obj = work/'oracle.o'
            # One independent C object is used by both Dyn lowering modes.
            subprocess.run([*CLANG, *flags, '-ffreestanding', '-fno-stack-protector',
                '-ffp-contract=off', '-O2', '-c', str(work/'oracle.c'), '-o', str(obj)],
                check=True, timeout=60)
            if target == 'thumbv7em-none':
                b.arm_addends(obj)
            for mode in ('ssa', 'tree'):
                env = dict(os.environ)
                env.pop('DYN_NO_SSA', None)
                if mode == 'tree':
                    env['DYN_NO_SSA'] = '1'
                image = work/f'{mode}.elf'
                build = subprocess.run([DYN, 'build', str(project), '--release', '--target', target,
                    '--no-cache', '--opt-remarks', '--link', str(obj), '--output', str(image)],
                    env=env, capture_output=True, text=True, timeout=120)
                log = build.stdout + build.stderr
                assert build.returncode == 0, (target, mode, log)
                check_remarks(log, mode)
                actual = run_guest([*qemu, *board, '-nographic', '-kernel', str(image)])
                expected = (0, b'ABI OK\n', b'')
                assert actual == expected, (target, mode, expected, actual)
                completed += 1
                print(f'PASS {target} {mode}: 164 named functions; Clang oracle status/output', flush=True)
    if completed:
        print(f'PASS aggregate-calls: {completed}/4 guests; 164 named SSA functions per target; '
              '164 missing-remark negative controls', flush=True)
    else:
        print('SKIP aggregate-calls: no QEMU targets executed', flush=True)


if __name__ == '__main__':
    main()
