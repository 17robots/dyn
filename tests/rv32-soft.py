#!/usr/bin/env python3
"""RV32IM/ILP32 integration: real Dyn float expressions, clang ABI, no FPU.

DYN and CLANG override compilers. DYN_QEMU_RISCV32 accepts a shell-split
wrapper; use TMPDIR on a path mounted at the same location in its container.
Container wrappers must bound the guest themselves (e.g. timeout 50).
Only missing tools skip; compilation, linking, decoding and guest failures fail.
"""
import os
from pathlib import Path
import shlex
import shutil
import signal
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
CLANG = shlex.split(os.environ.get('CLANG', 'clang'))
QEMU = shlex.split(os.environ.get('DYN_QEMU_RISCV32', 'qemu-system-riscv32'))
for tool in ([DYN], CLANG, QEMU):
    if not tool or not shutil.which(tool[0]):
        raise SystemExit('SKIP rv32-soft: missing prerequisite ' + str(tool))


def run(command, **kwargs):
    return subprocess.run(command, check=True, timeout=120, **kwargs)


def check_image(path):
    """Decode instruction boundaries in every SHF_EXECINSTR section, not data."""
    data = path.read_bytes()
    assert data[:7] == b'\x7fELF\x01\x01\x01', 'expected little-endian ELF32'
    assert struct.unpack_from('<HH', data, 16) == (2, 243)
    assert struct.unpack_from('<I', data, 36)[0] == 0, 'expected ELF flags 0 (ILP32, no RVC)'
    shoff = struct.unpack_from('<I', data, 32)[0]
    entsize, count = struct.unpack_from('<HH', data, 46)
    assert entsize == 40 and count > 0, 'missing section headers'
    instructions = 0
    for i in range(count):
        _, kind, flags, address, offset, size, *_ = struct.unpack_from('<10I', data, shoff + i * entsize)
        if not flags & 4:
            continue
        assert kind == 1 and offset + size <= len(data) and size % 4 == 0
        for pos in range(offset, offset + size, 4):
            word = struct.unpack_from('<I', data, pos)[0]
            assert word & 3 == 3 and word & 31 != 31, f'non-RV32IM instruction at {address + pos-offset:#x}: {word:#x}'
            assert word & 127 not in (0x07, 0x27, 0x43, 0x47, 0x4b, 0x4f, 0x53), f'FP opcode at {address + pos-offset:#x}: {word:#x}'
            # FP CSR reads/writes also require the absent floating extension.
            assert not (word & 127 == 0x73 and (word >> 12) & 7 and (word >> 20) in (1, 2, 3)), 'FP CSR instruction'
            instructions += 1
    assert instructions > 0
    return instructions


# Exact IEEE results, including cancellation, signed zero, subnormals and NaNs.
# C passes these opaque bits through a function pointer, preventing folding in Dyn.
C = ['#include <stdint.h>', '#include <stdarg.h>',
     'typedef union { float f; uint32_t u; } Fbits;',
     'typedef union { double f; uint64_t u; } Dbits;']
D = ['use "std/io"']
B = []
for width, one, two, seven, half, inf, nan, sign in (
        (32, 0x3f800000, 0x40000000, 0x40e00000, 0x3f000000, 0x7f800000, 0x7fc00000, 0x80000000),
        (64, 0x3ff0000000000000, 0x4000000000000000, 0x401c000000000000, 0x3fe0000000000000, 0x7ff0000000000000, 0x7ff8000000000000, 0x8000000000000000)):
    exprs = ['a+b', 'a-b', 'a*b', 'a/b', 'a%b']
    D += [f'fn arithmetic{width}(op:i32, x:u{width}, y:u{width}) u{width} {{',
          f'a := #bitcast(f{width}, x)\nb := #bitcast(f{width}, y)', 'case op {']
    D += [f'{i} => {{ return #bitcast(u{width}, {expr}) }}' for i, expr in enumerate(exprs)]
    D += [f'5 => {{ if a != b && !(a == b) && !(a < b) && !(a <= b) && !(a > b) && !(a >= b) {{ return 1 }}\nreturn 0 }}',
          '_ => { return 0 }', '}', '}']
    vectors = [(0, one, one, two), (1, one, one, 0), (2, two, half, one),
               (3, one, two, half), (4, seven, two, one), (4, seven | sign, two, one | sign),
               (0, 1, 1, 2), (1, 2, 1, 1), (2, 2, half, 1), (3, 2, two, 1),
               (4, 3, 2, 1), (2, 0, sign | one, sign), (3, one, 0, inf),
               (0, nan, one, nan), (3, 0, 0, nan), (4, inf, one, nan), (5, nan, one, 1)]
    C += [f'int arithmetic_check{width}(uint{width}_t (*fn)(int,uint{width}_t,uint{width}_t)) {{']
    C += [f'if(fn({op},UINT{width}_C({a}),UINT{width}_C({b})) != UINT{width}_C({expected})) return {i+1};'
          for i, (op, a, b, expected) in enumerate(vectors)]
    C += ['return 0; }']
    D += [f'extern fn arithmetic_check{width}(f:fn(i32,u{width},u{width}) u{width}) i32']
    B += [f'if arithmetic_check{width}(arithmetic{width}) != 0 {{ #panic("arithmetic f{width}") }}']

D += ['fn conversions(x:i64, y:u64, a:f32, b:f64) i32 {',
      'if #cast(f32,x) != -7.0 || #cast(f64,x) != -7.0 || #cast(f32,y) != 9.0 || #cast(f64,y) != 9.0 { return 1 }',
      'if #cast(i64,a) != -7 || #cast(i32,b) != 9 || #cast(u64,b) != 9 || #cast(u32,b) != 9 { return 2 }',
      'if #cast(f64,a) != -7.5 || #cast(f32,b) != 9.5 { return 3 }\nreturn 0 }',
      'extern fn conversion_check(f:fn(i64,u64,f32,f64) i32) i32']
C += ['int conversion_check(int (*fn)(int64_t,uint64_t,float,double)) { return fn(-7,9,(Fbits){.u=0xc0f00000}.f,(Dbits){.u=UINT64_C(0x4023000000000000)}.f); }']
B += ['if conversion_check(conversions) != 0 { #panic("conversions") }']
D += ['fn widen(x:u32) u64 { return #bitcast(u64,#cast(f64,#bitcast(f32,x))) }',
      'fn narrow(x:u64) u32 { return #bitcast(u32,#cast(f32,#bitcast(f64,x))) }',
      'extern fn width_check(w:fn(u32) u64,n:fn(u64) u32) i32']
C += ['int width_check(uint64_t (*w)(uint32_t),uint32_t (*n)(uint64_t)) {',
      'return w(1)==UINT64_C(0x36a0000000000000) && w(0x80000000)==UINT64_C(0x8000000000000000)',
      '&& n(UINT64_C(0x36a0000000000000))==1 && n(UINT64_C(0x3690000000000000))==0',
      '&& n(UINT64_C(0x3690000000000001))==1 && n(UINT64_C(0x3ff0000010000000))==0x3f800000',
      '&& n(UINT64_C(0x3ff0000010000001))==0x3f800001; }']
B += ['if width_check(widen,narrow) != 1 { #panic("width conversion rounding") }']


# Identity transforms isolate the ABI oracle from compiler-rt float operations.
# Scalars, small register aggregates and large indirect-return aggregates.
for name, ct, dt, ci, di, checks in (
    ('ScalarF', 'float', 'f32', '(Fbits){.u=0x3fc00000}.f', '1.5', [('','0x3fc00000','Fbits')]),
    ('ScalarD', 'double', 'f64', '(Dbits){.u=UINT64_C(0x4004000000000000)}.f', '2.5', [('','0x4004000000000000','Dbits')]),
    ('Pair', 'Pair', 'Pair', '{.a=(Fbits){.u=0x3fc00000}.f,.b=(Fbits){.u=0x40200000}.f}', 'Pair{a:1.5,b:2.5}', [('.a','0x3fc00000','Fbits'),('.b','0x40200000','Fbits')]),
    ('Large', 'Large', 'Large', '{.a=(Dbits){.u=UINT64_C(0x3ff8000000000000)}.f,.b=(Dbits){.u=UINT64_C(0x4004000000000000)}.f}', 'Large{a:1.5,b:2.5}', [('.a','0x3ff8000000000000','Dbits'),('.b','0x4004000000000000','Dbits')])):
    if name in ('Pair', 'Large'):
        ft, dft = ('float', 'f32') if name == 'Pair' else ('double', 'f64')
        C += [f'typedef struct {{ {ft} a,b; }} {name};']
        D += [f'struct {name} {{ a:{dft}, b:{dft} }}']
    for pressure in (0, 7, 8):
        key = f'{name}{pressure}'
        cp = [f'int g{i}' for i in range(pressure)] + [f'{ct} x', 'int tail']
        dp = [f'g{i}:i32' for i in range(pressure)] + [f'x:{dt}', 'tail:i32']
        args = [str(i+1) for i in range(pressure)] + ['x', '19']
        bad = ' || '.join([f'g{i}!={i+1}' for i in range(pressure)] + ['tail!=19'])
        valid = ' && '.join(f'({union}){{.f=r{field}}}.u == UINT64_C({bits})' for field,bits,union in checks)
        C += [f'{ct} c_{key}({",".join(cp)}) {{ if ({bad}) return ({ct}){{0}}; return x; }}',
              f'int cb_{key}({ct} (*fn)({",".join(cp)})) {{ {ct} x={ci}; {ct} r=fn({",".join(args)}); return {valid}; }}']
        D += [f'extern fn c_{key}({",".join(dp)}) {dt}',
              f'extern fn cb_{key}(f:fn({",".join(["i32"]*pressure+[dt,"i32"])}) {dt}) i32',
              f'fn local_{key}({",".join(dp)}) {dt} {{ if {bad} {{ #panic("incoming {key}") }}\nreturn x }}']
        B += [f'if cb_{key}(local_{key}) != 1 {{ #panic("callback {key}") }}',
              f'if cb_{key}(c_{key}) != 1 {{ #panic("C control {key}") }}',
              f'x_{key} := {di}', f'r_{key} := c_{key}({",".join(args).replace("x",f"x_{key}")})']
        for field, bits, union in checks:
            width = 32 if union == 'Fbits' else 64
            B += [f'if #bitcast(u{width},r_{key}{field}) != {bits} {{ #panic("outgoing {key}") }}']
C += ['int variadic(int tag, ...) { va_list ap; va_start(ap,tag); int a=va_arg(ap,int); double b=va_arg(ap,double); int c=va_arg(ap,int); va_end(ap); return tag==17 && a==23 && (Dbits){.f=b}.u==UINT64_C(0x4004000000000000) && c==29; }']
C += ['Pair named_variadic(Pair x, ...) { va_list ap; va_start(ap,x); int a=va_arg(ap,int); double b=va_arg(ap,double); va_end(ap); if(a!=23 || (Dbits){.f=b}.u!=UINT64_C(0x4004000000000000)) return (Pair){0}; return x; }']
D += ['extern fn named_variadic(x:Pair, ...) Pair']
B += ['v := named_variadic(Pair{a:1.5,b:2.5},23,#cast(f64,2.5))',
      'if v.a != 1.5 || v.b != 2.5 { #panic("named aggregate variadic") }']
D += ['extern fn variadic(tag:i32, ...) i32']
B += ['if variadic(17,23,#cast(f64,2.5),29) != 1 { #panic("variadic") }']

with tempfile.TemporaryDirectory(prefix='dyn-rv32-soft-') as tmp:
    work = Path(tmp)
    source = work / 'source'
    source.mkdir()
    (source / 'main.dyn').write_text('\n'.join(D) + '\nfn main() {\n' + '\n'.join(B) + '\n_ = io.write_all(io.stdout(), "RV32 SOFT PASS\\n")\n}\n')
    (work / 'oracle.c').write_text('\n'.join(C))
    common = [*CLANG, '--target=riscv32-unknown-elf', '-mno-relax', '-mcmodel=medany', '-ffreestanding', '-fno-stack-protector']
    (work / 'hard.c').write_text('int hard_marker(void) { return 1; }\n')
    hard = work / 'hard.o'
    run([*common, '-march=rv32imafd', '-mabi=ilp32d', '-c', str(work / 'hard.c'), '-o', str(hard)])
    for mode in ('debug', 'release'):
        obj, image = work / f'{mode}.o', work / f'{mode}.elf'
        run([*common, '-march=rv32im', '-mabi=ilp32', '-O0' if mode == 'debug' else '-O2', '-c', str(work / 'oracle.c'), '-o', str(obj)])
        command = [DYN, 'build', str(source), '--target', 'riscv32-none-soft', '--no-cache', '--quiet', f'--{mode}', '--link', str(obj), '--output', str(image)]
        run(command)
        instructions = check_image(image)
        rejected = subprocess.run([*command, '--link', str(hard)], capture_output=True, timeout=120)
        assert rejected.returncode != 0 and b'floating-point ABI' in rejected.stdout + rejected.stderr, 'mixed soft/hard objects must fail with an ABI diagnostic'
        # Rebuild since a failing linker is allowed to remove its output.
        run(command)
        guest = subprocess.Popen([*QEMU, '-machine', 'virt', '-cpu', 'sifive-e31', '-bios', 'none', '-nographic', '-kernel', str(image)],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            output, _ = guest.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            os.killpg(guest.pid, signal.SIGKILL)
            output, _ = guest.communicate()
            raise AssertionError(f'{mode} QEMU timeout: {output[-65536:]!r}')
        assert guest.returncode == 0 and b'RV32 SOFT PASS' in output, f'{mode}: status={guest.returncode} {output[-65536:]!r}'
        print(f'PASS rv32-soft {mode}: arithmetic/conversions, clang ABI, mixed ABI rejection; {instructions} integer instructions', flush=True)
