#!/usr/bin/env python3
"""Paired SSA on bare RV32/Thumb: named lowering checks and a clang oracle.

DYN and CLANG select compilers; ROOT overrides the compiler directory.
DYN_QEMU_RISCV32 / DYN_QEMU_ARM are shell-split command prefixes, as in
bare-metal.py. Container wrappers must mount TMPDIR at the identical path
and bound the guest lifetime (e.g. `timeout 20 qemu-system-arm`). The host
also bounds execution and kills the wrapper process group on timeout.
All fixtures and outputs live in TemporaryDirectory, respecting TMPDIR.
"""
import ast
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import struct
import subprocess
import tempfile

ROOT = Path(os.environ.get('ROOT', Path(__file__).resolve().parents[1])).resolve()
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
CLANG = shlex.split(os.environ.get('CLANG', 'clang'))
POSITIVE = 'literal_negative switch_negative aggregate_negative descriptor_negative indirect indirect_read array_negative floating add sub mul bits neg sl sr sa cmp cmpu narrow split cycle cycle3 branch memory readmem frame large shiftvar shruvar shrsvar checked division called'.split()
FALLBACK = []
TARGETS = (
    ('riscv32-none', 'DYN_QEMU_RISCV32', 'qemu-system-riscv32',
     ['--target=riscv32-unknown-elf', '-march=rv32imafd', '-mabi=ilp32d', '-mno-relax', '-mcmodel=medany'],
     ['-machine', 'virt', '-bios', 'none']),
    ('thumbv7em-none', 'DYN_QEMU_ARM', 'qemu-system-arm',
     ['--target=arm-none-eabihf', '-mcpu=cortex-m7', '-mthumb', '-mfpu=fpv5-d16', '-mfloat-abi=hard'],
     ['-machine', 'mps2-an500', '-semihosting-config', 'enable=on,target=native']),
)

DYN_SOURCE = r'''
use "std/io"
g8: i8
g16: u16
g32: i32
g64: u64
pub fn add(x:u64,y:u64) u64 { return #wrap(x+y) }
pub fn sub(x:u64,y:u64) u64 { return #wrap(x-y) }
pub fn mul(x:u64,y:u64) u64 { return #wrap(x*y) }
pub fn bits(x:u64,y:u64) u64 { return (x & y) ^ (x | ~y) }
pub fn neg(x:i64) i64 { return #wrap(-x) }
pub fn sl(x:u64) u64 { return #wrap(x << 33) }
pub fn sr(x:u64) u64 { return x >> 32 }
pub fn sa(x:i64) i64 { return x >> 63 }
pub fn cmp(x:i64,y:i64) bool { return x < y }
pub fn cmpu(x:u64,y:u64) bool { return x >= y }
pub fn narrow(x:i8,y:u16,z:i32) i64 { return #wrap(#cast(i64,x)+#cast(i64,y)+#cast(i64,z)) }
pub fn split(a:u32,b:u32,c:u32,d:u32,e:u32,f:u32,g:u32,x:u64,y:u32,z:u64) u64 {
  return #wrap(#cast(u64,a)+#cast(u64,b)+#cast(u64,c)+#cast(u64,d)+#cast(u64,e)+#cast(u64,f)+#cast(u64,g)+x+#cast(u64,y)+z)
}
pub fn cycle(x:u64,y:u64,n:u32) u64 {
  a:=x
  b:=y
  i:u32=0
  for i<n { t:=a
  a=b
  b=t
  i=#wrap(i+1) }
  return a
}
pub fn cycle3(x:u64,y:u64,z:u64,n:u32) u64 {
  a:=x
  b:=y
  c:=z
  i:u32=0
  for i<n { t:=a
  a=b
  b=c
  c=t
  i=#wrap(i+1) }
  return a
}
pub fn branch(x:i64,y:i64) i64 { if x>y { return x }
return y }
pub fn memory(a:i8,b:u16,c:i32,d:u64) u64 {
  g8=a
  g16=b
  g32=c
  g64=d
  return #wrap(#bitcast(u64,#cast(i64,g8))+#cast(u64,g16)+#bitcast(u64,#cast(i64,g32))+g64)
}
pub fn readmem() u64 { return #wrap(#bitcast(u64,#cast(i64,g8))+#cast(u64,g16)+#bitcast(u64,#cast(i64,g32))+g64) }
pub fn literal_negative(x:u64) u64 { if x==0 { #panic("fallback literal remains interned") }
return x }
pub fn checked(x:u64,y:u64) u64 { return x+y }
pub fn division(x:u64) u64 { return x/3 }
pub fn floating(x:f64) f64 { return x*2.0 }
pub fn called(x:u64) u64 { return add(x,1) }
extern fn oracle() i32
fn main() { if oracle()!=0 { #panic("oracle failed") }
_=io.write_all(io.stdout(),"SSA32 PASS\n") }

pub fn frame(x:u64) u64 { y:=x
p:=&y
p.*=#wrap(p.*+1)
return y }
pub fn shiftvar(x:u64,n:u64) u64 { return #wrap(x << (n & 63)) }
pub fn shruvar(x:u64,n:u64) u64 { return x >> (n & 63) }
pub fn shrsvar(x:i64,n:u64) i64 { return x >> (n & 63) }
pub fn indirect(p:*u64,x:u64) { p.*=x }
pub fn indirect_read(p:*u64) u64 { return p.* }
struct Pair { a:u64,b:u64 }
pub fn aggregate_negative(x:Pair) Pair { return x }
pub fn descriptor_negative(x:[]u8) usize { return #len(x) }
pub fn array_negative() u8 { a:[8]u8=[]
return a[0] }
pub fn switch_negative(x:i64) i64 {
 case x { 0=>{return 10}1=>{return 11}2=>{return 12}3=>{return 13}4=>{return 14}5=>{return 15}_=>{return 99} }
}
'''

C_SOURCE = r'''
typedef unsigned long long U; typedef long long I;
extern U add(U,U),sub(U,U),mul(U,U),bits(U,U),sl(U),sr(U),split(unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,U,unsigned,U),cycle(U,U,unsigned),cycle3(U,U,U,unsigned),memory(signed char,unsigned short,int,U),readmem(void);
extern I neg(I),sa(I),narrow(signed char,unsigned short,int),branch(I,I);
extern _Bool cmp(I,I),cmpu(U,U);
extern U shiftvar(U,U),shruvar(U,U),indirect_read(U*); extern I shrsvar(I,U); extern void indirect(U*,U);
extern U frame(U);
extern U large(LARGE_TYPES);
int oracle(void) {
 U xs[]={0,1,0xffffffffULL,0x100000000ULL,0x8000000000000000ULL,0xffffffffffffffffULL,0x123456789abcdef0ULL};
 for(unsigned i=0;i<7;i++) for(unsigned j=0;j<7;j++) {
  U x=xs[i],y=xs[j];
  if(add(x,y)!=x+y || sub(x,y)!=x-y || mul(x,y)!=x*y) return 1;
  if(bits(x,y)!=((x&y)^(x|~y)) || (U)neg((I)x)!=0-x) return 2;
  if(sl(x)!=(x<<33) || sr(x)!=(x>>32) || sa((I)x)!=((I)x>>63)) return 3;
  if(cmp((I)x,(I)y)!=((I)x<(I)y) || cmpu(x,y)!=(x>=y)) return 4;
  if(branch((I)x,(I)y)!=((I)x>(I)y?(I)x:(I)y)) return 5;
  for(unsigned n=0;n<7;n++) {
   if(cycle(x,y,n)!=(n%2?y:x)) return 6;
   if(cycle3(x,y,17,n)!=(n%3==0?x:n%3==1?y:17)) return 7;
  }
 }
 if(narrow(-121,65000,-123456789)!=-123391910LL) return 8;
 if(split(1,2,3,4,5,6,7,0x123456789abcdef0ULL,19,0xfedcba9876543210ULL)!=0x111111111111112fULL) return 9;
 U want=(U)-121+65000+(U)-123456789+0x123456789abcdef0ULL;
 if(memory(-121,65000,-123456789,0x123456789abcdef0ULL)!=want || readmem()!=want) return 10;
 if(frame(0xffffffffULL)!=0x100000000ULL) return 11;
 if(large(LARGE_ARGS)!=61425ULL) return 12;
 for(unsigned i=0;i<7;i++) for(unsigned n=0;n<64;n++) {
  U x=xs[i];
  if(shiftvar(x,n)!=(x<<n) || shruvar(x,n)!=(x>>n) || shrsvar((I)x,n)!=((I)x>>n)) return 13;
 }
 U cell=0; indirect(&cell,0xfedcba9876543210ULL); if(indirect_read(&cell)!=0xfedcba9876543210ULL) return 14;
 return 0;
}
'''


def arm_addends(path):
    # Load only the metadata adapter, never the sibling test's top-level code.
    source = ROOT/'tests/thumb-hfa-abi.py'
    tree = ast.parse(source.read_text())
    helper = next(node for node in tree.body
                  if isinstance(node, ast.FunctionDef) and node.name == 'explicit_arm_addends')
    namespace = {'struct': struct}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(source), 'exec'), namespace)
    namespace['explicit_arm_addends'](path)


def check_remarks(log, mode):
    remarks = {}
    for name, message in re.findall(r'^remark: (\w+): (.*)$', log, re.MULTILINE):
        remarks.setdefault(name, []).append(message)
    if mode == 'tree':
        assert 'SSA code generation' not in log, log
        return
    for name in POSITIVE:
        messages = remarks.get(name, [])
        assert any(message.startswith('SSA code generation,') for message in messages), (name, messages, log)
        assert not any('tree emitter' in message for message in messages), (name, messages)
    for name in FALLBACK:
        messages = remarks.get(name, [])
        assert 'tree emitter (paired SSA boundary)' in messages, (name, messages, log)
        assert not any('SSA code generation' in message for message in messages), (name, messages)
    assert any('699 paired frame slots' in message for message in remarks['large']), remarks['large']
    for name in ('cycle', 'cycle3'):
        assert any(re.search(r'[1-9]\d* phi temporaries', message) for message in remarks[name]), remarks[name]


def run_guest(command):
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise AssertionError(f'guest exceeded 30 seconds: {command}')
    assert process.returncode == 0, (command, process.returncode, stdout, stderr)
    stdout = stdout.replace(b'\r\n', b'\n')
    assert stdout == b'SSA32 PASS\n', (command, stdout, stderr)
    return stdout


def main():
    for label, command in [('DYN', [DYN]), ('CLANG', CLANG)]:
        if not command or not shutil.which(command[0]):
            print(f'SKIP bare SSA: {label} executable unavailable: {command}', flush=True)
            return
    completed = 0
    for target, variable, program, flags, board in TARGETS:
        qemu = shlex.split(os.environ.get(variable, '')) or [program]
        if not shutil.which(qemu[0]):
            print(f'SKIP {target}: {qemu[0]} unavailable; set {variable}', flush=True)
            continue
        with tempfile.TemporaryDirectory(prefix='dyn-bare-ssa-') as temporary:
            work = Path(temporary)
            # 350 parameter values plus 349 sums exercise a 699-slot SSA frame.
            large = ('pub fn large(' + ','.join(f'x{i}:u64' for i in range(350)) +
                     ') u64 { return #wrap(' + '+'.join(f'x{i}' for i in range(350)) + ') }\n')
            project = work/'source'
            project.mkdir()
            (project/'main.dyn').write_text(DYN_SOURCE + large)
            c = C_SOURCE.replace('LARGE_TYPES', ','.join(['U'] * 350))
            c = c.replace('LARGE_ARGS', ','.join(f'{i}ULL' for i in range(1, 351)))
            (work/'oracle.c').write_text(c)
            obj = work/'oracle.o'
            # This object is shared by both modes: clang supplies independent
            # machine code and calls exported Dyn functions across the C ABI.
            subprocess.run([*CLANG, *flags, '-ffreestanding', '-fno-stack-protector',
                            '-O2', '-c', str(work/'oracle.c'), '-o', str(obj)], check=True, timeout=60)
            if target == 'thumbv7em-none':
                arm_addends(obj)
            outputs = []
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
                assert build.returncode == 0, log
                check_remarks(log, mode)
                outputs.append(run_guest([*qemu, *board, '-nographic', '-kernel', str(image)]))
            assert outputs[0] == outputs[1], outputs
            completed += 1
            print(f'PASS {target}: {len(POSITIVE)} named SSA, {len(FALLBACK)} explicit fallbacks; '
                  'SSA/tree release match clang oracle (14 check groups, all 64 counts for left/logical-right/arithmetic-right shifts)', flush=True)
    if not completed:
        print('SKIP bare SSA: no QEMU targets executed', flush=True)


if __name__ == '__main__':
    main()
