#!/usr/bin/env python3
"""Thumb AAPCS-soft integration: real Dyn float expressions, clang ABI, no FPU.

DYN and CLANG override compilers. DYN_QEMU_ARM accepts a shell-split
wrapper; use TMPDIR on a path mounted at the same location in its container.
Container wrappers must bound the guest themselves (e.g. timeout 50).
Unflagged Clang ABI attribute validation is covered by arm-abi-attributes.py.
The final ELF must retain ARM mapping symbols, including generated Dyn code.
Only missing tools skip; compilation, linking, decoding and guest failures fail.
"""
import os
from pathlib import Path
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
CLANG = shlex.split(os.environ.get('CLANG', 'clang'))
QEMU = shlex.split(os.environ.get('DYN_QEMU_ARM', 'qemu-system-arm'))
for tool in ([DYN], CLANG, QEMU):
    if not tool or not shutil.which(tool[0]):
        print('SKIP thumb-soft: missing prerequisite ' + str(tool), flush=True)
        sys.exit(0)


def run(command, **kwargs):
    return subprocess.run(command, check=True, timeout=120, **kwargs)


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


def decode_thumb(data, address):
    """Decode T16/T32 boundaries; reject CP10/11 in both coprocessor spaces."""
    pos = count = 0
    while pos < len(data):
        assert pos + 2 <= len(data), 'truncated Thumb instruction'
        hi, = struct.unpack_from('<H', data, pos)
        wide = hi >> 11 in (0b11101, 0b11110, 0b11111)
        if wide:
            assert pos + 4 <= len(data), 'truncated Thumb-2 instruction'
            lo, = struct.unpack_from('<H', data, pos + 2)
            # ECxx-EFxx and FCxx-FFxx encode coprocessor instructions;
            # cp10/cp11 cover VFP loads/stores, arithmetic and transfers.
            assert not (hi & 0xEC00 == 0xEC00 and (lo >> 8) & 15 in (10, 11)), f'VFP instruction at {address+pos:#x}: {hi:04x} {lo:04x}'
        pos += 4 if wide else 2
        count += 1
    return count


def check_image(path):
    """Audit all executable bytes, honoring ARM $t/$d mapping symbols."""
    data = path.read_bytes()
    assert data[:7] == b'\x7fELF\x01\x01\x01'
    assert struct.unpack_from('<HH', data, 16) == (2, 40)
    flags, = struct.unpack_from('<I', data, 36)
    assert flags & 0x600 == 0x200, f'expected explicit soft ABI flags: {flags:#x}'
    shoff, = struct.unpack_from('<I', data, 32)
    entsize, count = struct.unpack_from('<HH', data, 46)
    assert entsize == 40 and count
    sections = [struct.unpack_from('<10I', data, shoff+i*entsize) for i in range(count)]
    mappings = {}
    for section in sections:
        if section[1] != 2:
            continue
        strings = sections[section[6]]
        names = data[strings[4]:strings[4]+strings[5]]
        for at in range(section[4], section[4]+section[5], 16):
            name, value, _, _, _, index = struct.unpack_from('<IIIBBH', data, at)
            name = names[name:].split(b'\0', 1)[0].split(b'.', 1)[0]
            if name in (b'$t', b'$d', b'$a'):
                mappings.setdefault(index, set()).add((value, name))
    instructions = 0
    for i, section in enumerate(sections):
        _, kind, flags, address, offset, size, *_ = section
        if not flags & 4 or not size:
            continue
        assert kind == 1 and offset + size <= len(data)
        marks = sorted(mappings.get(i, ()))
        assert marks and marks[0][0] == address, f'executable section {i} lacks initial mapping symbol'
        for (start, mode), (end, _) in zip(marks, marks[1:]+[(address+size, b'')]):
            assert address <= start <= end <= address+size
            assert mode != b'$a', 'ARM code in Cortex-M image'
            if mode == b'$t':
                instructions += decode_thumb(data[offset+start-address:offset+end-address], start)
    assert instructions
    return instructions


# Decoder controls cover narrow/wide boundaries and VFP instruction families.
assert decode_thumb(bytes.fromhex('00bf00f000f8'), 0) == 2
for encoding in ('b0ee400a', '2ded028b', '10ee100a'):
    try:
        decode_thumb(bytes.fromhex(encoding), 0)
    except AssertionError:
        pass
    else:
        raise AssertionError('VFP audit negative control failed')


def audit_controls(work):
    """Prove mapping-aware traversal skips literals but rejects executable VFP."""
    path = work / 'audit-control.elf'
    # ELF header, three sections, symbol table and strings. .text contains a
    # Thumb NOP then a VFP-shaped literal; $d must prevent a false positive.
    blob = bytearray(52 + 4*40)
    blob[:7] = b'\x7fELF\x01\x01\x01'
    struct.pack_into('<HH', blob, 16, 2, 40)
    struct.pack_into('<II', blob, 32, 52, 0x05000200)
    struct.pack_into('<HH', blob, 46, 40, 4)
    code = bytes.fromhex('00bfb0ee400a')
    code_offset = len(blob)
    blob += code
    symbol_offset = len(blob)
    blob += struct.pack('<IIIBBH', 1, 0x1000, 0, 0, 0, 1)
    blob += struct.pack('<IIIBBH', 4, 0x1002, 0, 0, 0, 1)
    string_offset = len(blob)
    blob += b'\0$t\0$d\0'
    struct.pack_into('<10I', blob, 92, 0, 1, 6, 0x1000, code_offset, len(code), 0, 0, 2, 0)
    struct.pack_into('<10I', blob, 132, 0, 2, 0, 0, symbol_offset, 32, 3, 0, 4, 16)
    struct.pack_into('<10I', blob, 172, 0, 3, 0, 0, string_offset, 7, 0, 0, 1, 0)
    path.write_bytes(blob)
    assert check_image(path) == 1
    # Treat the same literal as code: the audit must now fail.
    struct.pack_into('<I', blob, symbol_offset+16, 1)
    path.write_bytes(blob)
    try:
        check_image(path)
    except AssertionError as error:
        assert 'VFP instruction' in str(error), error
    else:
        raise AssertionError('mapping-aware VFP negative control failed')


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
    for pressure in (0, 1, 2, 3, 4, 7, 8):
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

# Volatile CPACR reads observe actual hardware state, before and after work.
C += ['uint32_t cpacr(void) { return *(volatile uint32_t *)0xe000ed88u; }']
D += ['extern fn cpacr() u32',
      'fn recursive(n:i32, x:f64, wide:u64) f64 { if n == 0 { return x }\nsaved := x + #cast(f64,wide)\nchild := recursive(n-1,x+0.5,wide+1)\nreturn child + saved }']
B.insert(0, 'if cpacr() & 0x00f00000 != 0 { #panic("CP10/11 enabled at entry") }')
B += ['if recursive(5,1.5,0x100000001) != 21474836511.5 { #panic("recursive frame bank") }',
      'if cpacr() & 0x00f00000 != 0 { #panic("CP10/11 enabled after work") }']


def guest_run(image, mode, panic=False):
    guest = subprocess.Popen([*QEMU, '-machine', 'mps2-an500',
                              '-semihosting-config', 'enable=on,target=native',
                              '-nographic', '-kernel', str(image)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, start_new_session=True)
    try:
        output, _ = guest.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        os.killpg(guest.pid, signal.SIGKILL)
        output, _ = guest.communicate(timeout=10)
        raise AssertionError(f'{mode} QEMU timeout: {output[-65536:]!r}')
    if panic:
        assert guest.returncode == 101 and b'runtime check failed' in output, (mode, guest.returncode, output)
        assert output.count(b'UNWIND BANK PASS') == 4, output
    else:
        assert guest.returncode == 0 and b'THUMB SOFT PASS' in output, (mode, guest.returncode, output)


with tempfile.TemporaryDirectory(prefix='dyn-thumb-soft-') as tmp:
    work = Path(tmp)
    audit_controls(work)
    source = work / 'source'
    source.mkdir()
    (source / 'main.dyn').write_text('\n'.join(D) + '\nfn main() {\n' + '\n'.join(B) + '\n_ = io.write_all(io.stdout(), "THUMB SOFT PASS\\n")\n}\n')
    (work / 'oracle.c').write_text('\n'.join(C))
    common = [*CLANG, '--target=arm-none-eabi', '-mcpu=cortex-m7', '-mthumb', '-ffreestanding', '-fno-stack-protector']
    (work / 'hard.c').write_text('int hard_marker(void) { return 1; }\n')
    hard = work / 'hard.o'
    run([*common, '-mfpu=fpv5-d16', '-mfloat-abi=hard', '-c', str(work / 'hard.c'), '-o', str(hard)])
    explicit_arm_addends(hard)
    # Clang ET_REL commonly leaves e_flags ABI bits unset, recording PCS in
    # .ARM.attributes instead. Mark this fixture explicitly to retain flag
    # rejection coverage; arm-abi-attributes.py tests unflagged objects.
    hard_data = bytearray(hard.read_bytes())
    hard_flags, = struct.unpack_from('<I', hard_data, 36)
    struct.pack_into('<I', hard_data, 36, (hard_flags & ~0x600) | 0x400)
    hard.write_bytes(hard_data)
    for mode in ('debug', 'release'):
        obj, image = work / f'{mode}.o', work / f'{mode}.elf'
        run([*common, '-mfloat-abi=soft', '-O0' if mode == 'debug' else '-O2', '-c', str(work / 'oracle.c'), '-o', str(obj)])
        explicit_arm_addends(obj)
        command = [DYN, 'build', str(source), '--target', 'thumbv7em-none-soft', '--no-cache', '--quiet', f'--{mode}', '--link', str(obj), '--output', str(image)]
        run(command)
        instructions = check_image(image)
        guest_run(image, mode)
        rejected = subprocess.run([*command, '--link', str(hard)], capture_output=True, timeout=120)
        assert rejected.returncode != 0 and b'ABI' in rejected.stdout + rejected.stderr, 'explicit mixed soft/hard objects must fail with an ABI diagnostic'
        print(f'PASS thumb-soft {mode}: arithmetic/conversions, recursive frame bank, CPACR disabled, clang ABI, explicit mixed ABI rejection; {instructions} non-VFP instructions', flush=True)
    # Checked bounds panic unwinds recursively through live f64/u64 locals.
    # Release disables bounds checks; debug is the contract exercised here.
    (source / 'main.dyn').write_text('use "std/io"\nextern fn cpacr() u32\nfn cleanup(x:f64, wide:u64) {\n  if x != 7.5 || wide != 0x123456789abcdef0 || cpacr() & 0x00f00000 != 0 { #panic("unwind bank corrupt") }\n  _ = io.println(io.stdout(), "UNWIND BANK PASS")\n}\nfn descend(n:i32, index:usize) {\n  x:f64 = 7.5\n  wide:u64 = 0x123456789abcdef0\n  defer cleanup(x,wide)\n  if n != 0 { descend(n-1,index)\n  return }\n  values:[1]u8 = [7]\n  _ = values[index]\n}\nfn main() { descend(3,2) }\n')
    image = work / 'panic.elf'
    run([DYN, 'build', str(source), '--target', 'thumbv7em-none-soft', '--no-cache', '--quiet', '--debug', '--link', str(obj), '--output', str(image)])
    check_image(image)
    guest_run(image, 'checked panic', panic=True)
    print('PASS thumb-soft checked panic: four recursive frame-bank cleanups', flush=True)
