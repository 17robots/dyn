#!/usr/bin/env python3
"""RV32 ILP32D structs against independent clang C, in both call directions.

Runs debug/release bare-metal images on QEMU virt. DYN_QEMU_RISCV32 may
contain a wrapper ending in qemu-system-riscv32 (see bare-metal.py).
The oracle checks every field, arguments after the aggregate, return registers,
FP exhaustion with seven/eight preceding doubles, and mixed GP exhaustion.
"""
import os
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
WORK = ROOT/'build/rv32-float-aggregate-abi'
WORK.mkdir(parents=True, exist_ok=True)
qemu = shlex.split(os.environ.get('DYN_QEMU_RISCV32', ''))
if not qemu:
    if not shutil.which('qemu-system-riscv32'):
        raise SystemExit('QEMU required: set DYN_QEMU_RISCV32 (see bare-metal.py)')
    qemu = ['qemu-system-riscv32']

# C fields, Dyn fields, initializer, scalar leaves and their original values.
cases = [
    ('F', 'float a;', 'a:f32', 'a:1.5', [('a', 1.5)]),
    ('D', 'double a;', 'a:f64', 'a:1.5', [('a', 1.5)]),
    ('FF', 'float a,b;', 'a:f32,b:f32', 'a:1.5,b:2.5', [('a',1.5),('b',2.5)]),
    ('DD', 'double a,b;', 'a:f64,b:f64', 'a:1.5,b:2.5', [('a',1.5),('b',2.5)]),
    ('FD', 'float a; double b;', 'a:f32,b:f64', 'a:1.5,b:2.5', [('a',1.5),('b',2.5)]),
    ('DF', 'double a; float b;', 'a:f64,b:f32', 'a:1.5,b:2.5', [('a',1.5),('b',2.5)]),
    ('DI', 'double a; int b;', 'a:f64,b:i32', 'a:1.5,b:-7', [('a',1.5),('b',-7)]),
    ('ID', 'unsigned char a; double b;', 'a:u8,b:f64', 'a:7,b:2.5', [('a',7),('b',2.5)]),
    ('FI', 'float a; short b;', 'a:f32,b:i16', 'a:1.5,b:-7', [('a',1.5),('b',-7)]),
    ('IF', 'int a; float b;', 'a:i32,b:f32', 'a:-7,b:2.5', [('a',-7),('b',2.5)]),
    ('Nested', 'struct { double a[2]; } v;', 'v:Inner', 'v:Inner{a:[1.5,2.5]}', [('v.a[0]',1.5),('v.a[1]',2.5)]),
    # Negative classification controls: >XLEN integer leaf and >2 leaves.
    ('Wide', 'double a; long long b;', 'a:f64,b:i64', 'a:1.5,b:7', [('a',1.5),('b',7)]),
    ('FFF', 'float a,b,c;', 'a:f32,b:f32,c:f32', 'a:1.5,b:2.5,c:3.5', [('a',1.5),('b',2.5),('c',3.5)]),
    ('II', 'int a,b;', 'a:i32,b:i32', 'a:7,b:9', [('a',7),('b',9)]),
]
c = []
dyn = ['use "std/io"', 'struct Inner { a:[2]f64 }']
body = []
checks = 0
for name, cf, df, init, leaves in cases:
    c.append(f'typedef struct {{ {cf} }} {name};')
    dyn.append(f'struct {name} {{ {df} }}')
    pressures = [(0,0), (7,0), (8,0)]
    if name in ('DI','ID'):
        pressures += [(0,8), (8,8)]
    for nf, ng in pressures:
        key = f'{name}_{nf}_{ng}'
        cp = [f'double f{i}' for i in range(nf)] + [f'int g{i}' for i in range(ng)]
        dp = [f'f{i}:f64' for i in range(nf)] + [f'g{i}:i32' for i in range(ng)]
        args = [f'{i+1}.0' for i in range(nf)] + [str(i+1) for i in range(ng)]
        cp += [f'{name} x', 'int tail']
        dp += [f'x:{name}', 'tail:i32']
        valid = [f'f{i} != {i+1}.0' for i in range(nf)] + [f'g{i} != {i+1}' for i in range(ng)]
        valid += [f'x.{path} != {value}' for path,value in leaves] + ['tail != 19']
        cond = ' || '.join(valid)
        updates = ' '.join(f'x.{path} += 1;' for path,_ in leaves)
        c += [f'{name} c_{key}({",".join(cp)}) {{ if ({cond}) return ({name}){{0}}; {updates} return x; }}']
        # C supplies its own aggregate, invokes Dyn and checks its returned struct.
        cinit = ' '.join(f'x.{path} = {value};' for path,value in leaves)
        result = ' && '.join(f'r.{path} == {value+1}' for path,value in leaves)
        c += [f'int cb_{key}({name} (*fn)({",".join(cp)})) {{ {name} x = {{0}}; {cinit} '
              f'{name} r = fn({",".join(args+["x","19"])}); return {result}; }}']
        dyn += [f'extern fn c_{key}({",".join(dp)}) {name}',
                f'extern fn cb_{key}(f:fn({",".join(["f64"]*nf+["i32"]*ng+[name,"i32"])}) {name}) i32',
                f'fn local_{key}({",".join(dp)}) {name} {{ if {cond} {{ #panic("incoming {key}") }} '
                f'y := x '+ ' '.join(f'y.{path} += {1.0 if isinstance(value,float) else 1}' for path,value in leaves) + ' return y }']
        body += [f'x_{key} := {name}{{{init}}}',
                 f'r_{key} := c_{key}({",".join(args+[f"x_{key}","19"])})',
                 'if ' + ' || '.join(f'r_{key}.{path} != {value+1} || x_{key}.{path} != {value}' for path,value in leaves) +
                 f' {{ #panic("outgoing {key}") }}',
                 f'if cb_{key}(local_{key}) != 1 {{ #panic("return {key}") }}']
        body += [f'fn_{key} := c_{key}',
                 f'r_{key} = fn_{key}({",".join(args+[f"x_{key}","19"])})',
                 'if ' + ' || '.join(f'r_{key}.{path} != {value+1}' for path,value in leaves) +
                 f' {{ #panic("indirect {key}") }}']
        checks += 3
# Named aggregates retain FP classification in a variadic function. The
# frontend currently rejects aggregates in unnamed C variadic positions.
c += ['#include <stdarg.h>',
      'DD named_variadic(DD x, ...) { va_list ap; va_start(ap,x); int n=va_arg(ap,int); va_end(ap); x.a += n; return x; }']
dyn += ['extern fn named_variadic(x:DD, ...) DD']
body += ['v := named_variadic(DD{a:1.5,b:2.5},3)',
         'if v.a != 4.5 || v.b != 2.5 { #panic("named variadic") }']
checks += 1
(WORK/'provider.c').write_text('\n'.join(c)+'\n')
source = WORK/'source'
source.mkdir(exist_ok=True)
(source/'main.dyn').write_text('\n'.join(dyn)+'\nfn main() {\n'+'\n'.join(body)+
                              '\n_ = io.write_all(io.stdout(), "RV32 ABI PASS\\n")\n}\n')
for release in (False, True):
    mode = 'release' if release else 'debug'
    obj, image = WORK/f'{mode}.o', WORK/f'{mode}.elf'
    subprocess.run([*shlex.split(os.environ.get('CLANG','clang')), '--target=riscv32-unknown-elf',
                    '-march=rv32imafd', '-mabi=ilp32d', '-mno-relax', '-mcmodel=medany',
                    '-ffreestanding', '-fno-stack-protector', '-O2' if release else '-O0',
                    '-c', str(WORK/'provider.c'), '-o', str(obj)], check=True)
    subprocess.run([DYN, 'build', str(source), '--target', 'riscv32-none', '--no-cache', '--quiet',
                    '--link', str(obj), '--output', str(image)] + (['--release'] if release else []),
                   check=True, timeout=120)
    ran = subprocess.run([*qemu, '-machine','virt','-bios','none','-nographic','-kernel',str(image)],
                         capture_output=True, timeout=60)
    if ran.returncode or b'RV32 ABI PASS' not in ran.stdout:
        raise SystemExit(f'FAIL {mode}: status {ran.returncode}\n{ran.stdout.decode(errors="replace")}\n{ran.stderr.decode(errors="replace")}')
    print(f'PASS RV32 ILP32D {mode}: {checks} clang/Dyn direction checks', flush=True)
