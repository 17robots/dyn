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
