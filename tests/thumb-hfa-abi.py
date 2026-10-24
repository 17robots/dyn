#!/usr/bin/env python3
"""Thumb AAPCS-VFP HFA clang interop in debug/release, both directions.

DYN_QEMU_ARM accepts a full container wrapper; images use TMPDIR so that
wrapper only needs to mount the shared temporary directory. CLANG and DYN
select the independent C compiler and Dyn compiler.
"""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import signal
import struct

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
temporary = tempfile.TemporaryDirectory(prefix='dyn-thumb-hfa-')
WORK = Path(temporary.name)
qemu = shlex.split(os.environ.get('DYN_QEMU_ARM', ''))
if not qemu:
    if not shutil.which('qemu-system-arm'):
        raise SystemExit('QEMU required: set DYN_QEMU_ARM (see bare-metal.py)')
    qemu = ['qemu-system-arm']

def explicit_arm_addends(path):
    """Bridge clang REL to the built-in linker's explicit-addend dialect.

    Only relocation metadata changes; clang's argument/result instructions
    remain untouched. EHABI unwind indexes are unused by this bare-metal test.
    Dyn's Thumb branch relocations already subtract the PC bias themselves.
    """
    data = bytearray(path.read_bytes())
    shoff, = struct.unpack_from('<I', data, 32)
    entsize, count = struct.unpack_from('<HH', data, 46)
    sections = [list(struct.unpack_from('<10I', data, shoff+i*entsize)) for i in range(count)]
    for section in sections:
        if section[1] == 0x70000001:  # SHT_ARM_EXIDX
            section[2] = 0
            section[5] = 0
        if section[1] != 9:  # SHT_REL
            continue
        target = sections[section[7]]
        converted = bytearray()
        if target[1] != 0x70000001:
            for at in range(section[4], section[4]+section[5], 8):
                offset, info = struct.unpack_from('<II', data, at)
                kind = info & 255
                loc = target[4]+offset
                if kind in (2, 3):
                    addend, = struct.unpack_from('<i', data, loc)
                elif kind in (10, 30):
                    hi, lo = struct.unpack_from('<HH', data, loc)
                    sign = (hi >> 10) & 1
                    value = (sign<<24) | ((1 ^ ((lo>>13)&1) ^ sign)<<23) | ((1 ^ ((lo>>11)&1) ^ sign)<<22) | ((hi&1023)<<12) | ((lo&2047)<<1)
                    addend = value - (1<<25) if sign else value
                    addend += 4
                elif kind in (47, 48):
                    hi, lo = struct.unpack_from('<HH', data, loc)
                    addend = ((hi&15)<<12) | (((hi>>10)&1)<<11) | (((lo>>12)&7)<<8) | (lo&255)
                    if kind == 48:
                        addend <<= 16
                    if addend >= 1<<31:
                        addend -= 1<<32
                else:
                    raise AssertionError(f'unhandled clang ARM relocation {kind}')
                converted += struct.pack('<IIi', offset, info, addend)
        data += bytes((-len(data)) % 4)
        section[1], section[4], section[5], section[9] = 4, len(data), len(converted), 12
        data += converted
    for i, section in enumerate(sections):
        struct.pack_into('<10I', data, shoff+i*entsize, *section)
    path.write_bytes(data)


# C fields, Dyn fields, initializer, scalar leaves and their original values.
cases = []
for kind, ct in [('f32','float'), ('f64','double')]:
    for n in range(1,5):
        fields = list('abcd'[:n])
        cases.append((f'H{n}_{kind}', f'{ct} '+','.join(fields)+';',
                      ','.join(f'{f}:{kind}' for f in fields),
                      ','.join(f'{f}:{i+1}.5' for i,f in enumerate(fields)),
                      [(f,i+1.5) for i,f in enumerate(fields)]))
cases += [('Nested', 'struct { double a[2]; } v;', 'v:Inner',
           'v:Inner{a:[1.5,2.5]}', [('v.a[0]',1.5),('v.a[1]',2.5)])]
c = []
dyn = ['use "std/io"', 'struct Inner { a:[2]f64 }']
body = []
checks = 0
for name, cf, df, init, leaves in cases:
    c.append(f'typedef struct {{ {cf} }} {name};')
    dyn.append(f'struct {name} {{ {df} }}')
    # Holes from f32,f64 allow a one-float HFA to backfill s1; larger
    # HFAs must find a contiguous range. Fourteen singles leave only two
    # slots: larger HFAs spill whole and close even the remaining holes.
    pressures = [[], ['f64']*7, ['f64']*8, ['f32','f64'],
                 ['f32']*14, ['f32']+['f64']*7,
                 ['i32']*5+['f64']*8, ['i32','f32','f64','i64']]
    for scenario, prefix in enumerate(pressures):
        key = f'{name}_{scenario}'
        ctypes = {'f32':'float','f64':'double','i32':'int','i64':'long long'}
        cp = [f'{ctypes[t]} p{i}' for i,t in enumerate(prefix)]
        dp = [f'p{i}:{t}' for i,t in enumerate(prefix)]
        args = [f'{i+1}.0' if t.startswith('f') else str(i+1) for i,t in enumerate(prefix)]
        cp += [f'{name} x', 'int tail', 'float after', 'double last']
        dp += [f'x:{name}', 'tail:i32', 'after:f32', 'last:f64']
        valid = [f'p{i} != {value}' for i,value in enumerate(args)]
        valid += [f'x.{path} != {value}' for path,value in leaves] + ['tail != 19', 'after != 6.5', 'last != 7.5']
        cond = ' || '.join(valid)
        updates = ' '.join(f'x.{path} += 1;' for path,_ in leaves)
        c += [f'{name} c_{key}({",".join(cp)}) {{ if ({cond}) return ({name}){{0}}; {updates} return x; }}']
        # C supplies its own aggregate, invokes Dyn and checks its returned struct.
        cinit = ' '.join(f'x.{path} = {value};' for path,value in leaves)
        result = ' && '.join(f'r.{path} == {value+1}' for path,value in leaves)
        c += [f'int cb_{key}({name} (*fn)({",".join(cp)})) {{ {name} x = {{0}}; {cinit} '
              f'{name} r = fn({",".join(args+["x","19","6.5","7.5"])}); return {result}; }}']
        dyn += [f'extern fn c_{key}({",".join(dp)}) {name}',
                f'extern fn cb_{key}(f:fn({",".join(prefix+[name,"i32","f32","f64"])}) {name}) i32',
                f'fn local_{key}({",".join(dp)}) {name} {{ if {cond} {{ #panic("incoming {key}") }} '
                f'y := x '+ ' '.join(f'y.{path} += {1.0 if isinstance(value,float) else 1}' for path,value in leaves) + ' return y }']
        body += [f'x_{key} := {name}{{{init}}}',
                 f'r_{key} := c_{key}({",".join(args+[f"x_{key}","19","6.5","7.5"])})',
                 'if ' + ' || '.join(f'r_{key}.{path} != {value+1} || x_{key}.{path} != {value}' for path,value in leaves) +
                 f' {{ #panic("outgoing {key}") }}',
                 f'if cb_{key}(local_{key}) != 1 {{ #panic("return {key}") }}']
        body += [f'fn_{key} := c_{key}',
                 f'r_{key} = fn_{key}({",".join(args+[f"x_{key}","19","6.5","7.5"])})',
                 'if ' + ' || '.join(f'r_{key}.{path} != {value+1}' for path,value in leaves) +
                 f' {{ #panic("indirect {key}") }}']
        checks += 3
# C variadic functions use base PCS for named scalars, aggregates and
# results. Exhaust core registers first to avoid the separately scoped
# core/stack aggregate splitting rule. H1_f32 additionally checks r0 return.
c += ['#include <stdarg.h>']
for name, _, _, init, leaves in cases:
    key = f'var_{name}'
    valid = ' || '.join(f'x.{path} != {value}' for path,value in leaves)
    c += [f'{name} {key}(int a,int b,int c,int d,float f,double g,int pad,{name} x, ...) {{ '
          f'va_list ap; va_start(ap,x); int n=va_arg(ap,int); va_end(ap); '
          f'if(a!=1 || b!=2 || c!=3 || d!=4 || f!=6.5 || g!=7.5 || pad!=9 || n!=3 || {valid}) return ({name}){{0}}; '
          + ' '.join(f'x.{path} += n;' for path,_ in leaves) + ' return x; }']
    dyn += [f'extern fn {key}(a:i32,b:i32,c:i32,d:i32,f:f32,g:f64,pad:i32,x:{name}, ...) {name}']
    for indirect in (False,True):
        suffix = f'{key}_{int(indirect)}'
        if indirect:
            body += [f'fp_{key} := {key}']
        call = f'fp_{key}' if indirect else key
        body += [f'r_{suffix} := {call}(1,2,3,4,6.5,7.5,9,{name}{{{init}}},3)',
                 'if '+ ' || '.join(f'r_{suffix}.{path} != {value+3}' for path,value in leaves)+
                 f' {{ #panic("variadic {suffix}") }}']
        checks += 1
# Single-member base-PCS aggregate in core registers, including hidden sret.
for name in ('H1_f32','H1_f64'):
    key = f'core_{name}'
    c += [f'{name} {key}({name} x, ...) {{ va_list ap; va_start(ap,x); int n=va_arg(ap,int); va_end(ap); x.a += n; return x; }}']
    dyn += [f'extern fn {key}(x:{name}, ...) {name}']
    body += [f'fp_{key} := {key}', f'a_{key} := {key}({name}{{a:1.5}},3)',
             f'b_{key} := fp_{key}({name}{{a:1.5}},3)',
             f'if a_{key}.a != 4.5 || b_{key}.a != 4.5 {{ #panic("{key}") }}']
    checks += 2
# Scalar variadic returns also use r0/r1, with all named FP args in core
# registers/stack. This checks the result path alongside the HFA base PCS.
for kind, ct in [('f32','float'), ('f64','double')]:
    key = f'scalar_{kind}'
    c += [f'{ct} {key}(float a,double b, ...) {{ va_list ap; va_start(ap,b); int n=va_arg(ap,int); va_end(ap); return a+b+n; }}']
    dyn += [f'extern fn {key}(a:f32,b:f64, ...) {kind}']
    body += [f'fp_{key} := {key}', f'a_{key} := {key}(1.5,2.5,3)',
             f'b_{key} := fp_{key}(1.5,2.5,3)',
             f'if a_{key} != 7.0 || b_{key} != 7.0 {{ #panic("{key}") }}']
    checks += 2
(WORK/'provider.c').write_text('\n'.join(c)+'\n')
source = WORK/'source'
source.mkdir(exist_ok=True)
(source/'main.dyn').write_text('\n'.join(dyn)+'\nfn main() {\n'+'\n'.join(body)+
                              '\n_ = io.write_all(io.stdout(), "THUMB HFA PASS\\n")\n}\n')
for release in (False, True):
    mode = 'release' if release else 'debug'
    obj, image = WORK/f'{mode}.o', WORK/f'{mode}.elf'
    subprocess.run([*shlex.split(os.environ.get('CLANG','clang')), '--target=arm-none-eabihf',
                    '-mcpu=cortex-m7', '-mthumb', '-mfpu=fpv5-d16', '-mfloat-abi=hard',
                    '-ffreestanding', '-fno-stack-protector', '-O2' if release else '-O0',
                    '-c', str(WORK/'provider.c'), '-o', str(obj)], check=True)
    explicit_arm_addends(obj)
    subprocess.run([DYN, 'build', str(source), '--target', 'thumbv7em-none', '--no-cache', '--quiet',
                    '--link', str(obj), '--output', str(image)] + (['--release'] if release else []),
                   check=True, timeout=120)
    process = subprocess.Popen([*qemu, '-machine','mps2-an500',
                               '-semihosting-config','enable=on,target=native',
                               '-nographic','-kernel',str(image)], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise SystemExit(f'FAIL {mode}: QEMU timed out')
    ran = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
    if ran.returncode or b'THUMB HFA PASS' not in ran.stdout:
        raise SystemExit(f'FAIL {mode}: status {ran.returncode}\n{ran.stdout.decode(errors="replace")}\n{ran.stderr.decode(errors="replace")}')
    print(f'PASS Thumb AAPCS-VFP {mode}: {checks} clang/Dyn direction checks', flush=True)
