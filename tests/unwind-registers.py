#!/usr/bin/env python3
"""Preserve nonvolatile SIMD state when panic skips native function epilogues.

Linux x64 also executes Windows ABI instruction bodies with ms_abi helpers;
this is an ABI harness, not a claim of native Windows execution.
"""
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import struct
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve()
CLANG = shlex.split(os.environ.get('CLANG', 'clang'))


def run(command, expected=0):
    result = subprocess.run(list(map(str, command)), capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == expected, (command, result.returncode,
                                           result.stdout, result.stderr)
    return result


SOURCE = '''extern fn input "audit_input"() f64
extern fn cleanup "audit_cleanup"(v: f64)
extern fn opaque "audit_opaque"()
fn child(v: f64) {
  defer cleanup(v)
  opaque()
  if v > 0.0 { #panic("float unwind") }
}
fn parent(v: f64) { defer cleanup(v) child(v + 1.0) }
fn main() { parent(input()) }
'''

HOST_RUNTIME = r'''
#include <stdio.h>
#include <stdlib.h>
#define MS __attribute__((ms_abi))
struct frame { struct frame *previous; unsigned long long saved[31]; };
static struct frame *top;
static unsigned count;
static double seen[2];
extern MS void dyn_unwind_jump(struct frame *);
MS void dyn_unwind_link(struct frame *f) { f->previous=top; top=f; }
MS void dyn_unwind_unlink(struct frame *f) { top=f->previous; }
MS void dyn_unwind_continue(void) {
  if (top) {
    struct frame *f=top; top=f->previous; dyn_unwind_jump(f);
    abort();
  }
  printf("cleanup values: %.2f %.2f\n", seen[0], seen[1]);
  exit(!(count==2 && seen[0]==2.25 && seen[1]==1.25));
}
MS void dyn_panic(const char *s, unsigned long long n) {
  (void)s; (void)n; dyn_unwind_continue();
}
MS double audit_input(void) { return 1.25; }
MS void audit_opaque(void) { }
MS void audit_cleanup(double d) { if (count<2) seen[count++]=d; }
extern MS void dyn_entry(void);
int main(void) { dyn_entry(); }
'''


def windows_as_elf(assembly):
    """Change object-format directives only; leave instructions intact."""
    lines = []
    for line in assembly.splitlines():
        token = line.strip()
        if token.startswith(('.def', '.scl', '.type', '.endef', '.seh_',
                             '.globl\t@feat', '@feat.')):
            continue
        if token.startswith('.section\t.rdata'):
            line = '.section .rodata'
        if token == '.globl\t_fltused':
            continue
        if token == '.globl\tmain':
            line = '.globl dyn_entry'
        if token == 'main:':
            line = 'dyn_entry:'
        lines.append(line.replace('__real@', '__real_'))
    return '\n'.join(lines) + '\n.section .note.GNU-stack,"",@progbits\n'


def register_probe():
    # SysV entry into Windows set/jump, with shadow space and a deliberately
    # eight-byte-aligned context. Check full 128-bit values, not just doubles.
    lines = ['.text', '.global probe', 'probe:', 'push %rbx',
             'sub $368, %rsp', 'lea 40(%rsp), %rbx',
             'stmxcsr 304(%rsp)', 'fnstcw 308(%rsp)',
             'movl $0x1f80, 312(%rsp)', 'movw $0x037f, 316(%rsp)',
             'ldmxcsr 312(%rsp)', 'fldcw 316(%rsp)',
             'movq $12345, 296(%rsp)']
    for reg in range(6, 16):
        lines.append(f'movdqu seed+{16*(reg-6)}(%rip), %xmm{reg}')
    lines += ['mov %rbx, %rcx', 'call dyn_unwind_set',
              'test %eax, %eax', 'jnz restored']
    for reg in range(6, 16):
        lines.append(f'pxor %xmm{reg}, %xmm{reg}')
    lines += ['movl $0x3f80, 312(%rsp)', 'movw $0x077f, 316(%rsp)',
              'ldmxcsr 312(%rsp)', 'fldcw 316(%rsp)',
              'mov %rbx, %rcx', 'call dyn_unwind_jump', 'ud2', 'restored:']
    for reg in range(6, 16):
        lines += [f'pcmpeqb seed+{16*(reg-6)}(%rip), %xmm{reg}',
                  f'pmovmskb %xmm{reg}, %eax', 'cmp $65535, %eax', 'jne failed']
    lines += ['cmpq $12345, 296(%rsp)', 'jne failed',
              'stmxcsr 312(%rsp)', 'fnstcw 316(%rsp)',
              'cmpl $0x1f80, 312(%rsp)', 'jne failed',
              'cmpw $0x037f, 316(%rsp)', 'jne failed',
              'xor %eax, %eax', 'jmp finish', 'failed:', 'mov $1, %eax',
              'finish:', 'ldmxcsr 304(%rsp)', 'fldcw 308(%rsp)',
              'add $368, %rsp', 'pop %rbx', 'ret',
              '.section .rodata', '.p2align 4', 'seed:']
    for reg in range(6, 16):
        lines.append(f'.quad {reg}, {reg+100}')
    lines.append('.section .note.GNU-stack,"",@progbits')
    return '\n'.join(lines) + '\n'



def atomic_bodies(path, macho):
    """Read emitted atomics without requiring a host-specific disassembler."""
    data = path.read_bytes()
    sections, symbols = {}, {}
    if macho:
        assert data[:4] == b'\xcf\xfa\xed\xfe'
        at, section_id = 32, 1
        for _ in range(struct.unpack_from('<I', data, 16)[0]):
            command, size = struct.unpack_from('<II', data, at)
            if command == 0x19:  # LC_SEGMENT_64
                for index in range(struct.unpack_from('<I', data, at + 64)[0]):
                    entry = at + 72 + index * 80
                    address, length, offset = struct.unpack_from('<QQI', data, entry + 32)
                    sections[section_id] = (address, length, offset)
                    section_id += 1
            elif command == 2:  # LC_SYMTAB
                symoff, count, stroff, _ = struct.unpack_from('<IIII', data, at + 8)
            at += size
        for index in range(count):
            name, kind, section, _, address = struct.unpack_from('<IBBHQ', data, symoff + index * 16)
            if section and (kind & 0x0e) == 0x0e:
                name = data[stroff + name:].split(b'\0', 1)[0].decode()
                symbols[name.removeprefix('_')] = (section, address)
    else:
        assert data[:6] == b'\x7fELF\x02\x01'
        table = struct.unpack_from('<Q', data, 40)[0]
        stride, count = struct.unpack_from('<HH', data, 58)
        headers = [struct.unpack_from('<IIQQQQIIQQ', data, table + index * stride)
                   for index in range(count)]
        for index, header in enumerate(headers):
            sections[index] = (header[3], header[5], header[4])
        for header in headers:
            if header[1] != 2:  # SHT_SYMTAB
                continue
            strings = headers[header[6]][4]
            for at in range(header[4], header[4] + header[5], header[9]):
                name, _, _, section, address, _ = struct.unpack_from('<IBBHQQ', data, at)
                if section in sections and name:
                    name = data[strings + name:].split(b'\0', 1)[0].decode()
                    symbols[name] = (section, address)
    bodies = {}
    for name, (section, address) in symbols.items():
        if not name.startswith('dyn_atomic_'):
            continue
        base, length, offset = sections[section]
        end = min([value for candidate_section, value in symbols.values()
                   if candidate_section == section and value > address] + [base + length])
        bodies[name] = data[offset + address - base:offset + end - base]
    return bodies


def check_macos_atomics(root):
    # Equivalent handwritten ARM64 routines must survive both ELF and Mach-O
    # assembly. Darwin treats ';' as comments; accepting the source is not proof
    # that retry/return instructions made it into the object.
    linux = atomic_bodies(root / 'aarch64-linux-runtime.o', False)
    macos = atomic_bodies(root / 'aarch64-macos-runtime.o', True)
    expected = {f'dyn_atomic_{operation}_u{width}' for width in (32, 64)
                for operation in ('load', 'store', 'exchange', 'fetch_add', 'compare_exchange')}
    assert linux.keys() == macos.keys() == expected
    ret = bytes.fromhex('c0035fd6')
    for name in sorted(expected):
        body = macos[name]
        assert body == linux[name], (name, 'Darwin atomics lost or changed emitted instructions',
                                     body.hex(), linux[name].hex())
        instructions = [body[at:at + 4] for at in range(0, len(body), 4)]
        assert instructions[-1] == ret, (name, 'missing final return')
        assert instructions.count(ret) == (2 if 'compare_exchange' in name else 1), name
    print('PASS ARM64 atomic emitted instructions and return paths (ELF/Mach-O)')

with tempfile.TemporaryDirectory(prefix='dyn-unwind-registers-') as temporary:
    root = Path(temporary)
    (root / 'main.dyn').write_text(SOURCE)
    if not shutil.which(CLANG[0]):
        raise AssertionError('unwind ABI regression requires clang')

    # Assemble the actual target runtimes and compile the nested-defer fixture
    # for every affected ABI, even where native execution is unavailable.
    for target, triple, source, words in (
        ('x86_64-windows', 'x86_64-pc-windows-msvc', 'windows_x86_64_start.S', 32),
        ('aarch64-linux', 'aarch64-linux-gnu', 'linux_aarch64_start.S', 22),
        ('aarch64-macos', 'arm64-apple-macos11', 'macos_aarch64_start.S', 22),
        ('x86_64-linux', 'x86_64-linux-gnu', 'linux_x86_64_start.S', 16),
    ):
        run([*CLANG, '--target=' + triple, '-c', ROOT / 'runtime' / source,
             '-o', root / (target + '-runtime.o')])
        layout = root / (target + '-layout.c')
        layout.write_text('#include "' + (ROOT / 'runtime/reference_support.c').as_posix() + '"\n'
                          f'_Static_assert(sizeof(DynUnwind) == {words * 8}, "unwind size");\n'
                          '_Static_assert(offsetof(DynUnwind, saved) == 8, "unwind prefix");\n')
        run([*CLANG, '--target=' + triple, '-ffreestanding', '-c', layout,
             '-o', root / (target + '-support.o')])
        run([DYN, 'build', root, '--target', target, '--release', '--no-cache',
             '--jobs', '1', '--emit-asm', '--emit-ir', '--no-link',
             '--output', root / target])
        ir = (root / (target + '.ll')).read_text()
        assert re.search(r'alloca \[' + str(words) + r' x i64\]', ir), (
            target, 'incorrect unwind context size')
    check_macos_atomics(root)
    print('PASS native ABI runtime objects and target-sized compiler contexts (cross)')
    # Object assembly alone misses unresolved runtime imports. Link an actual
    # deferred cleanup program with freshly built support and the shipped ABI
    # metadata, without relying on the host SDK or import libraries.
    smoke = root / 'link-smoke'
    smoke.mkdir()
    (smoke / 'main.dyn').write_text('fn cleanup() {}\nfn main() { defer cleanup() }\n')
    for target, linker, flags in (
        ('x86_64-windows', 'lld-link', ['/entry:dyn_start', '/subsystem:console', '/nodefaultlib']),
        ('aarch64-macos', 'ld64.lld', ['-arch', 'arm64', '-platform_version', 'macos', '15.0', '15.0', '-e', '_dyn_start']),
    ):
        executable = run([*CLANG, '-print-prog-name=' + linker]).stdout.strip()
        for mode in ('--debug', '--release'):
            output = root / (target + mode + '-link')
            run([DYN, 'build', smoke, '--target', target, mode, '--no-cache',
                 '--emit-object', '--no-link', '--output', output])
            inputs = [root / (target + '-runtime.o'), root / (target + '-support.o'),
                      Path(str(output) + '.o')]
            if target == 'aarch64-macos':
                inputs.append(ROOT / 'runtime/libSystem.tbd')
            destination = ['/out:' + str(output)] if target == 'x86_64-windows' else ['-o', output]
            run([executable, *flags, *destination, *inputs])
    print('PASS Windows/macOS runtime imports resolve in debug/release links')

    if platform.system() == 'Linux' and platform.machine().lower() in ('x86_64', 'amd64'):
        source = (ROOT / 'runtime/windows_x86_64_start.S').read_text()
        source = source[source.index('.global dyn_unwind_set'):
                        source.index('.global dyn_trace_push')]
        runtime = root / 'windows-unwind.S'
        runtime.write_text(source + '\n.section .note.GNU-stack,"",@progbits\n')
        (root / 'probe.S').write_text(register_probe())
        (root / 'probe.c').write_text('extern int probe(void); int main(void) { return probe(); }\n')
        run([*CLANG, root / 'probe.c', root / 'probe.S', runtime, '-o', root / 'probe'])
        run([root / 'probe'])
        print('PASS Windows ABI full XMM6-XMM15, FP control, alignment and context bounds (Linux host)')

        # The generated parent and child both retain their capture in XMM6.
        # A skipped child epilogue used to make parent cleanup see 2.25 too.
        (root / 'generated.S').write_text(windows_as_elf(
            (root / 'x86_64-windows.s').read_text()))
        (root / 'host.c').write_text(HOST_RUNTIME)
        run([*CLANG, '-O2', root / 'host.c', root / 'generated.S', runtime,
             '-o', root / 'nested'])
        result = run([root / 'nested'])
        assert result.stdout == 'cleanup values: 2.25 1.25\n', result.stdout
        print('PASS compiler-generated Windows nested floating-point defers (Linux ABI harness)')
    else:
        print('SKIP Windows ABI host execution: requires x86-64 Linux')

    native = root / 'native'
    native.mkdir()
    (native / 'main.dyn').write_text('use "std/io"\n' + SOURCE.replace(
        'extern fn cleanup "audit_cleanup"(v: f64)', '''fn cleanup(v: f64) {
  if v == 2.25 { _ = io.println(io.stdout(), "child") }
  else if v == 1.25 { _ = io.println(io.stdout(), "parent") }
  else { _ = io.println(io.stdout(), "corrupted") }
}'''))
    (native / 'input.c').write_text('double audit_input(void) { return 1.25; }\n'
                                  'void audit_opaque(void) {}\n')
    helper = native / 'input.o'
    run([*CLANG, '-c', native / 'input.c', '-o', helper])
    for mode in ('debug', 'release'):
        output = native / ('program.exe' if os.name == 'nt' else 'program')
        run([DYN, 'build', native, '--' + mode, '--no-cache', '--jobs', '1',
             '--link', helper, '--output', output])
        result = run([output], expected=101)
        assert result.stdout == 'child\nparent\n', (mode, result.stdout)
        assert 'float unwind' in result.stderr, (mode, result.stderr)
    print('PASS native nested floating-point defers, debug/release')
