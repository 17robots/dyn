#!/usr/bin/env python3
"""Check Clang's x64 signed PC-relative addends without requiring a macOS host."""
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
clang = shutil.which(os.environ.get('CLANG', 'clang'))
if not clang:
    print('SKIP Mach-O relocation oracle: needs Clang')
    raise SystemExit(0)


def image(path):
    data = path.read_bytes()
    sections, symbols = [], {}
    at = 32
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, size = struct.unpack_from('<II', data, at)
        if cmd == 0x19:
            for i in range(struct.unpack_from('<I', data, at + 64)[0]):
                section = at + 72 + i * 80
                address, length, offset = struct.unpack_from('<QQI', data, section + 32)
                sections.append((address, length, offset))
        if cmd == 2:
            symoff, count, stroff, _ = struct.unpack_from('<IIII', data, at + 8)
            for i in range(count):
                name, _, _, _, value = struct.unpack_from('<IBBHQ', data, symoff + i * 16)
                end = data.index(b'\0', stroff + name)
                symbols[data[stroff + name:end].decode()] = value
        at += size
    return data, sections, symbols


with tempfile.TemporaryDirectory(prefix='dyn-macho-relocations-') as directory:
    work = Path(directory)
    (work/'driver.c').write_text('#include "link_macho.h"\nint main(int n,char **v) { DynMachOOptions o={.entry="_start"}; return dyn_link_macho((const char *const *)(v+2),n-2,v[1],&o); }\n')
    subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), '-std=c11', '-I', str(ROOT/'src'),
                    str(work/'driver.c'), str(ROOT/'src/link_macho.c'), '-o', str(work/'link')], check=True)
    asm = ['.text', '.globl _start', '_start:']
    checks = []
    for target in ('_value', 'Llocal'):
        for suffix, immediate_bytes in (('b', 1), ('w', 2), ('l', 4), ('q', 4)):
            label = f'_end_{len(checks)}'
            asm += [f'mov{suffix} $1, {target}(%rip)', f'.globl {label}', f'{label}:']
            checks.append((label, target, immediate_bytes))
    asm += ['ret', '.data', '.globl _value', '_value: .quad 0',
            '.globl _local_address', '_local_address:', 'Llocal: .quad 0']
    (work/'test.s').write_text('\n'.join(asm)+'\n')
    subprocess.run([clang, '-target', 'x86_64-apple-macos11', '-c', str(work/'test.s'), '-o', str(work/'test.o')], check=True)
    subprocess.run([str(work/'link'), str(work/'test'), str(work/'test.o')], check=True)
    data, sections, symbols = image(work/'test')
    for end, target, immediate_bytes in checks:
        next_pc = symbols[end]
        displacement_address = next_pc - immediate_bytes - 4
        section = next(s for s in sections if s[0] <= displacement_address < s[0]+s[1])
        displacement = struct.unpack_from('<i', data, section[2]+displacement_address-section[0])[0]
        expected = symbols['_local_address' if target == 'Llocal' else target]
        assert next_pc + displacement == expected, (end, hex(next_pc+displacement), hex(expected))
print('PASS Mach-O x64 SIGNED_1/2/4 external and section-relative addends')
