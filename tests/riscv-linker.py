#!/usr/bin/env python3
"""Qualify RV64 ELF relocations against assembler objects and QEMU execution.

Clang is an optional test oracle, never a production compiler dependency.
Set DYN_RISCV_SYSROOT to a sysroot containing lib/ld-linux-riscv64-lp64d.so.1
for the dynamic-loader test as well as the freestanding execution check.
"""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import struct
import tempfile

ROOT = Path(__file__).resolve().parents[1]
clang = shutil.which(os.environ.get('CLANG', 'clang'))
qemu = shutil.which('qemu-riscv64')
if not clang or not qemu:
    print('SKIP RV64 linker oracle: needs Clang and qemu-riscv64')
    raise SystemExit(0)

DRIVER = r'''
#include "link_elf.h"
#include <string.h>
int main(int argc,char **argv) { DynLinkOptions o={.entry="_start",.interpreter="/lib/ld-linux-riscv64-lp64d.so.1"}; int at=2; if(argc>2&&!strcmp(argv[2],"--shared")) {o.shared=1;at++;} return dyn_link_elf((const char *const *)(argv+at),argc-at,argv[1],&o); }
'''
STATIC = r'''
.option norelax
.option norvc
.text
.global _start
_start:
    call helper
    li t0, 42
    bne a0,t0,bad
.Ldata:
    auipc t0,%pcrel_hi(value)
    ld t1,%pcrel_lo(.Ldata)(t0)
    bne t1,a0,bad
.Lgot:
    auipc t0,%got_pcrel_hi(value)
    ld t0,%pcrel_lo(.Lgot)(t0)
    ld t1,0(t0)
    bne t1,a0,bad
    li a0,0
    j done
bad:
    li a0,7
done:
    li a7,93
    ecall
helper:
    li a0,42
    ret
.data
value:
    .quad 42
'''
DYNAMIC = r'''
.option norelax
.option norvc
.text
.global _start
_start:
    call helper
    li t0, 42
    bne a0,t0,bad
.Lgot:
    auipc t0,%got_pcrel_hi(value)
    ld t0,%pcrel_lo(.Lgot)(t0)
    ld t1,0(t0)
    bne t1,a0,bad
    li a0,0
    j done
bad:
    li a0,7
done:
    li a7,93
    ecall
'''
LIBRARY = r'''
.option norelax
.option norvc
.text
.global helper
.type helper,@function
helper:
 addi sp,sp,-16
 sd ra,8(sp)
 call nested
 ld ra,8(sp)
 addi sp,sp,16
 ret
.global nested
.type nested,@function
nested:
 li a0,42
 ret
.data
.global value
.type value,@object
value:
 .quad 42
.size value,8
'''

with tempfile.TemporaryDirectory(prefix='dyn-riscv-linker-') as directory:
    work = Path(directory)
    (work/'driver.c').write_text(DRIVER)
    subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-I'+str(ROOT/'src'), str(work/'driver.c'), str(ROOT/'src/link_elf.c'),
                    '-o', str(work/'link')], check=True)
    for name, source in [('static', STATIC), ('dynamic', DYNAMIC), ('library', LIBRARY)]:
        (work/(name+'.S')).write_text(source)
        subprocess.run([clang, '--target=riscv64-linux-gnu', '-march=rv64imafd', '-mabi=lp64d',
                        '-c', str(work/(name+'.S')), '-o', str(work/(name+'.o'))], check=True)
    subprocess.run([str(work/'link'), str(work/'static'), str(work/'static.o')], check=True)
    subprocess.run([qemu, str(work/'static')], check=True, timeout=10)
    subprocess.run([str(work/'link'), str(work/'library.so'), '--shared', str(work/'library.o')], check=True)
    subprocess.run([str(work/'link'), str(work/'dynamic'), str(work/'dynamic.o'), str(work/'library.so')], check=True)
    sysroot = Path(os.environ.get('DYN_RISCV_SYSROOT', '/usr/riscv64-linux-gnu'))
    if (sysroot/'lib/ld-linux-riscv64-lp64d.so.1').exists():
        subprocess.run([qemu, '-L', str(sysroot), str(work/'dynamic')], check=True, timeout=10)
        print('PASS RV64 dynamic PLT calls and imported GOT data')
        compiler = Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve()
        if compiler.exists():
            library = work/'dyn-library';library.mkdir()
            client = work/'dyn-client';client.mkdir()
            (library/'main.dyn').write_text('pub value:i64 = 5\npub fn calculate(x:i64) i64 { value += x return value }\n')
            (client/'main.dyn').write_text('extern fn calculate(x:i64) i64\nfn main() { if calculate(7) != 12 || calculate(3) != 15 { #panic("shared") } }\n')
            for mode in ('debug','release'):
                shared = work/('dyn-'+mode+'.so');executable = work/('client-'+mode)
                subprocess.run([str(compiler),'build',str(library),'--target','riscv64-linux','--'+mode,'--shared','--output',str(shared)],check=True)
                subprocess.run([str(compiler),'build',str(client),'--target','riscv64-linux','--'+mode,'--link',str(shared),'--output',str(executable)],check=True)
                subprocess.run([qemu,'-L',str(sysroot),str(executable)],check=True,timeout=10)
            print('PASS generated RV64 debug/release shared libraries, calls and mutable global data')

    else:
        print('SKIP RV64 dynamic execution: set DYN_RISCV_SYSROOT')
    incompatible = bytearray((work/'static.o').read_bytes())
    struct.pack_into('<I', incompatible, 48, 0)  # LP64 soft-float cannot mix with LP64D.
    (work/'soft.o').write_bytes(incompatible)
    result = subprocess.run([str(work/'link'), str(work/'soft'), str(work/'soft.o')], capture_output=True)
    assert result.returncode != 0 and b'LP64D ABI' in result.stderr, result.stderr
    # Malformed HI/LO pair must fail closed rather than encoding a bad address.
    broken = bytearray((work/'static.o').read_bytes())
    headers = struct.unpack_from('<Q', broken, 40)[0]
    count = struct.unpack_from('<H', broken, 60)[0]
    symbol_index = None
    relocations = []
    for index in range(count):
        header = headers + index * 64
        kind = struct.unpack_from('<I', broken, header + 4)[0]
        offset, size = struct.unpack_from('<QQ', broken, header + 24)
        if kind == 2:
            strings_index = struct.unpack_from('<I', broken, header + 40)[0]
            strings = struct.unpack_from('<Q', broken, headers + strings_index * 64 + 24)[0]
            for symbol in range(size // 24):
                name = strings + struct.unpack_from('<I', broken, offset + symbol * 24)[0]
                if broken[name:broken.index(0, name)] == b'value': symbol_index = symbol
        elif kind == 4:
            relocations.extend(range(offset, offset + size, 24))
    assert symbol_index is not None
    for offset in relocations:
        info = struct.unpack_from('<Q', broken, offset + 8)[0]
        if info & 0xffffffff == 24:
            struct.pack_into('<Q', broken, offset + 8, symbol_index << 32 | 24)
            break
    else:
        raise AssertionError('fixture has no LO12 relocation')
    (work/'broken.o').write_bytes(broken)
    result = subprocess.run([str(work/'link'), str(work/'broken'), str(work/'broken.o')], capture_output=True)
    assert result.returncode != 0 and b'HI20 pair' in result.stderr, result.stderr
print('PASS RV64 ELF calls, branches, PC-relative and GOT HI/LO pairs, absolute data and malformed pairs')
