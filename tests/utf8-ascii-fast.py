#!/usr/bin/env python3
"""UTF-8 validity against Python's strict decoder; DYN selects the compiler.

Functional checks pass before and after the ASCII optimization. Retain fixtures
with DYN_UTF8_ARTIFACTS; this is a correctness test, with no timing assertions.
"""
import itertools
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import struct
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
CLANG = shlex.split(os.environ.get('CLANG', 'clang'))


def valid(data):
    try:
        data.decode('utf-8', errors='strict')
        return 1
    except UnicodeDecodeError:
        return 0


def cases():
    yield b''
    yield from (bytes([b]) for b in range(256))
    yield from (bytes(pair) for pair in itertools.product(range(256), repeat=2))
    # Exhaust every lead/second-byte boundary, with representative remaining
    # continuations and invalid bytes. This covers overlongs and surrogates.
    for lead in range(0xe0, 0xf5):
        for second in range(256):
            for rest in (b'\x80\x80', b'\xbf\xbf', b'\x7f\x80', b'\xc0\x80'):
                data = bytes([lead, second]) + rest[:1 if lead < 0xf0 else 2]
                yield data
                yield data[:-1]
    for cp in (0, 127, 128, 2047, 2048, 0xd7ff, 0xe000, 0xffff, 0x10000, 0x10ffff):
        data = chr(cp).encode('utf-8')
        for prefix in range(len(data)):
            yield data[:prefix]
        for offset in range(17):
            yield b'a' * offset + data + b'z' * (32 - offset)
    for n in (1, 7, 8, 15, 16, 31, 32, 63, 64, 127, 128, 255, 256):
        yield bytes(i % 128 for i in range(n))
        for offset in range(min(n, 17)):
            yield b'a' * offset + b'\xf4\x90\x80\x80' + b'z' * n


SOURCE = '''use "std/unicode/utf8" utf8
use "std/io" io
extern fn exercise(check:fn(*const u8,usize) i32) i32
fn check(data:*const u8,length:usize) i32 {
  if utf8.valid(data[..length]) { return 1 }
  return 0
}
fn main() {
  if exercise(&check) != 0 { #panic("UTF8 reference mismatch") }
  _=io.println(io.stdout(),"UTF8 PASS")
}
'''


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


def run(work):
    corpus = list(dict.fromkeys(cases()))
    # A packed byte stream keeps the C fixture small. Every vector is checked
    # at every alignment; sentinels outside the slice must not affect validity.
    packed = bytearray()
    for data in corpus:
        packed.extend((len(data) & 255, len(data) >> 8, valid(data)))
        packed.extend(data)
    c = ['#include <stddef.h>', '#include <stdint.h>',
         'static const unsigned char corpus[] = {']
    c += [','.join(str(x) for x in packed[i:i+64])+',' for i in range(0, len(packed), 64)]
    c += ['};', '''int exercise(int (*check)(const unsigned char *,size_t)) {
      unsigned char buffer[1024];
      for(size_t p=0;p<sizeof(corpus);) {
        size_t n=corpus[p] + ((size_t)corpus[p+1]<<8); int expected=corpus[p+2]; p+=3;
        for(size_t offset=0;offset<16;offset++) {
          for(size_t i=0;i<sizeof(buffer);i++) buffer[i]=255;
          for(size_t i=0;i<n;i++) buffer[offset+i]=corpus[p+i];
          if(check(buffer+offset,n)!=expected) return 1;
        }
        p+=n;
      }
      return 0;
    }''']
    source = work / 'source'
    source.mkdir(exist_ok=True)
    (source / 'main.dyn').write_text(SOURCE)
    oracle = work / 'oracle.c'
    oracle.write_text('\n'.join(c))
    targets = [('', [], [])]
    for target, env, qemu, args, flags in (
        ('riscv32-none-soft','DYN_QEMU_RISCV32','qemu-system-riscv32',
         ['-machine','virt','-cpu','sifive-e31','-bios','none','-nographic','-kernel'],
         ['--target=riscv32-unknown-elf','-march=rv32im','-mabi=ilp32','-mno-relax','-mcmodel=medany']),
        ('thumbv7em-none-soft','DYN_QEMU_ARM','qemu-system-arm',
         ['-machine','mps2-an500','-nographic','-semihosting-config','enable=on,target=native','-kernel'],
         ['--target=arm-none-eabi','-mcpu=cortex-m7','-mthumb','-mfloat-abi=soft'])):
        wrapper = shlex.split(os.environ.get(env, qemu))
        if wrapper and shutil.which(wrapper[0]):
            targets.append((target, flags, wrapper + args))
        else:
            print('SKIP UTF8', target, '(missing QEMU; set '+env+')', flush=True)
    for target, flags, runner in targets:
        for mode in ('debug', 'release'):
            name = (target or 'host') + '-' + mode
            obj, output = work / (name+'.o'), work / name
            subprocess.run([*CLANG,*flags,'-ffreestanding','-fno-stack-protector','-O2','-c',str(oracle),'-o',str(obj)], check=True, timeout=120)
            if target.startswith('thumb'):
                explicit_arm_addends(obj)
            command = [DYN,'build',str(source),'--no-cache','--quiet','--'+mode,'--link',str(obj),'--output',str(output)]
            if target:
                command += ['--target',target]
            subprocess.run(command, cwd=ROOT, check=True, timeout=120)
            result = subprocess.run([*runner,str(output)], capture_output=True, timeout=60)
            assert result.returncode == 0 and b'UTF8 PASS' in result.stdout, (name,result.returncode,result.stdout,result.stderr)
            print('PASS UTF8',name,len(corpus),'Python reference vectors, 16 alignments',flush=True)


if __name__ == '__main__':
    retained = os.environ.get('DYN_UTF8_ARTIFACTS')
    if retained:
        work = Path(retained).resolve()
        work.mkdir(parents=True,exist_ok=True)
        run(work)
    else:
        with tempfile.TemporaryDirectory(prefix='dyn-utf8-') as temporary:
            run(Path(temporary))
