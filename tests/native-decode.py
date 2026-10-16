#!/usr/bin/env python3
"""Independent decoder annotations must reassemble to the oracle's encodings."""
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CC = shlex.split(os.environ.get('CC', 'cc'))
CLANG = shutil.which(os.environ.get('CLANG', 'clang'))
def run(*args):
    p = subprocess.run(list(map(str, args)), text=True, capture_output=True, timeout=90)
    assert p.returncode == 0, (args, p.stdout, p.stderr)
    return p.stdout

def text_section(path):
    data = path.read_bytes()
    assert data[:5] == b'\x7fELF\x02'
    offset = struct.unpack_from('<Q', data, 40)[0]
    size, count, names = struct.unpack_from('<HHH', data, 58)
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, offset+i*size) for i in range(count)]
    strings = sections[names]
    table = data[strings[4]:strings[4]+strings[5]]
    for section in sections:
        name = table[section[0]:].split(b'\0')[0]
        if name == b'.text':
            return data[section[4]:section[4]+section[5]]
    raise AssertionError('no text')

x64 = [
    'push r12', 'pop r15', 'mov r15, rax', 'mov rax, r15',
    'mov qword ptr [rbp-48], r12', 'mov r13, qword ptr [rbp-48]',
    'mov ah, al', 'mov spl, al', 'mov al, ah',
    'mov byte ptr [rax], 1', 'cmp byte ptr [rax], 0',
    'call rax', 'jmp r11', 'push qword ptr [rsp+8]',
    'add rax, -1', 'sub rax, -128', 'and rax, -256', 'imul rax, rcx, -1234',
    'mov eax, 0xffffffff', 'mov rax, -1', 'test rax, -1',
    'movzx eax, al', 'movsx rax, byte ptr [rax]', 'movsxd rax, dword ptr [rsi]',
    'lea rax, [rbp-48]', 'lea rax, [r12+r13*4-128]',
    'movq xmm0, rax', 'movq rax, xmm0', 'movd xmm0, eax', 'movd eax, xmm0',
    'movq xmm0, qword ptr [rsp]', 'movss xmm0, dword ptr [rax]',
    'movsd qword ptr [rax], xmm0', 'cvtsi2ss xmm0, rax',
    'cvtsi2sd xmm0, eax', 'cvttss2si rax, xmm0', 'cvttsd2si eax, xmm0',
    'cvtss2sd xmm0, xmm1', 'cvtsd2ss xmm0, xmm1', 'xorps xmm0, xmm0',
    'ucomiss xmm0, xmm1', 'ucomisd xmm0, xmm1', 'addss xmm0, xmm1', 'subsd xmm0, xmm1',
    'movdqu xmm0, xmmword ptr [rsi]', 'movdqu xmmword ptr [r11], xmm0',
    'paddd xmm0, xmm1', 'paddq xmm0, xmm1', 'psubd xmm0, xmm1', 'psubq xmm0, xmm1',
    'pand xmm0, xmm1', 'por xmm0, xmm1', 'pxor xmm0, xmm1',
    'shlx rax, rax, rcx', 'shrx rax, rax, rcx', 'sarx rax, rax, rcx',
    'ret', 'leave', 'nop', 'int3', 'cld', 'std', 'cqo', 'ud2', 'syscall',
]
arm = [
    'stp x29, x30, [sp, #-16]!', 'ldp x29, x30, [sp], #16',
    'stp xzr, xzr, [sp, #16]', 'ldnp x0, x1, [sp, #32]',
    'str x19, [x29, #-48]', 'ldr x22, [x29, #-48]',
    'mov x0, xzr', 'mov x29, sp', 'orn x0, xzr, x0', 'bic x0, x1, x2',
    'eon x0, x1, x2', 'bics xzr, x1, x2',
    'sub sp, sp, #48', 'add wsp, wsp, #16', 'subs xzr, x0, #1',
    'movz x0, #42', 'movk x0, #42, lsl #48', 'movn w0, #1',
    'strb w0, [x1, #3]', 'ldrb w0, [x1, #3]', 'strh w0, [x1, #2]',
    'stur b0, [x1, #-1]',  # Unsupported FP byte loads fail closed below.
    'sturb w0, [x1, #-1]', 'ldurh w0, [x1, #-2]', 'ldur xzr, [sp, #-8]',
    'ldr q0, [x14]', 'str q0, [x12, #16]', 'ldur q0, [x1, #-16]',
    'add v0.4s, v0.4s, v1.4s', 'add v0.2d, v0.2d, v1.2d',
    'sub v0.4s, v0.4s, v1.4s', 'sub v0.2d, v0.2d, v1.2d',
    'and v0.16b, v0.16b, v1.16b', 'orr v0.16b, v0.16b, v1.16b', 'eor v0.16b, v0.16b, v1.16b',
    'b.eq .+8', 'b.ne .-4', 'b .+12', 'bl .-8', 'ret', 'blr x16', 'br x16', 'svc #0',
]
with tempfile.TemporaryDirectory(prefix='dyn-decoder-') as directory:
    work = Path(directory)
    c = work/'decode.c'
    c.write_text(r'''#include "native_decode.h"
#include <stdlib.h>
int main(int argc, char **argv) {
  if (argc != 3) return 2;
  unsigned char bytes[32]; size_t n = strlen(argv[2])/2;
  if (n > sizeof bytes) return 2;
  for (size_t i=0; i<n; ++i) { unsigned x; if (sscanf(argv[2]+2*i,"%2x",&x)!=1) return 2; bytes[i]=(unsigned char)x; }
  char out[512]={0}; size_t got = !strcmp(argv[1],"x64") ? nd_x64(bytes,n,out,sizeof out) : !strcmp(argv[1],"a64") ? nd_a64(bytes,n,out,sizeof out) : nd_rv64(bytes,n,out,sizeof out);
  printf("%zu\n%s\n",got,out); return 0;
}
''')
    decoder = work/('decode.exe' if os.name == 'nt' else 'decode')
    run(*CC, '-std=c11', '-Wall', '-Wextra', '-Werror', '-I'+str(ROOT/'src'), c, '-o', decoder)
    def decode(arch, data):
        lines = run(decoder, arch, data.hex()).splitlines()
        return int(lines[0]), lines[1] if len(lines) > 1 else ''
    # Known regressions stay checked even when no reference assembler is present.
    for arch, raw, expected in (
        ('x64', 'ffd0', 'call rax'), ('x64', '4883c0ff', 'add rax, -1'),
        ('x64', '88e0', 'mov al, ah'), ('x64', '4088e0', 'mov al, spl'),
        ('a64', '40000054', 'b.eq .+8'), ('a64', '0084a14e', 'add v0.4s, v0.4s, v1.4s'),
        ('a64', 'c001c03d', 'ldr q0, [x14, #0]')):
        data=bytes.fromhex(raw)
        assert decode(arch,data) == (len(data),expected), (arch,raw,decode(arch,data))
    for raw in ('f090', 'f30f6e00', '0f6fc0', 'c7f800000000', 'f34889c0'):
        assert decode('x64', bytes.fromhex(raw))[0] == 0, raw
    if CLANG and os.environ.get('DYN_ASSEMBLY_ORACLE', '1') != '0':
        for arch, target, examples in (('x64','x86_64-linux-gnu',x64), ('a64','aarch64-linux-gnu',arm)):
            for original in examples:
                assembly = work/'input.s'; obj = work/'input.o'
                header = '.text\n' + ('.intel_syntax noprefix\n' if arch == 'x64' else '')
                assembly.write_text(header + original + '\n')
                run(CLANG, '--target='+target, '-c', assembly, '-o', obj)
                encoded = text_section(obj)
                length, decoded = decode(arch, encoded)
                if original.startswith('stur b0'):
                    assert length == 0
                    continue
                assert length == len(encoded), (arch, original, encoded.hex(), length, decoded)
                assembly.write_text(header + decoded + '\n')
                run(CLANG, '--target='+target, '-c', assembly, '-o', obj)
                assert text_section(obj) == encoded, (arch,original,decoded,encoded.hex(),text_section(obj).hex())
print('PASS decoder widths, signed immediates, branch targets, SIMD and independent assembler roundtrips')
