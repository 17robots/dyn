#!/usr/bin/env python3
"""Calls to C variadic functions compile to SSA code on the 64-bit targets.

SSA once sent every function that called a C variadic function, directly or
through a function pointer, to the tree emitter there. It now follows each platform's variadic convention: AL holds
the vector register count on System V x86-64, Microsoft x64 repeats float
arguments in their integer registers, RISC-V passes variadic floats in
integer registers, Windows on Arm passes all floats of the call that way and
Apple AArch64 passes variadic arguments on the stack. A freestanding C
provider reads mixed integer, double and pointer arguments past the register
files. Runnable targets compare SSA, tree (DYN_NO_SSA=1) and debug builds;
macOS and Windows on Arm are cross-linked only."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
PROVIDER = r'''
#include <stdarg.h>
/* kinds: i int, l long long, d double, p pointer to long long. */
double mix(const char *kinds, ...) {
  va_list ap; va_start(ap, kinds);
  double total = 0, scale = 1;
  for (const char *k = kinds; *k; ++k, scale += 1) {
    if (*k == 'i') total += scale * va_arg(ap, int);
    else if (*k == 'l') total += scale * (double)va_arg(ap, long long);
    else if (*k == 'd') total += scale * va_arg(ap, double);
    else if (*k == 'p') total += scale * (double)*va_arg(ap, long long *);
  }
  va_end(ap);
  return total;
}
double mix_again(const char *kinds, ...) {
  va_list ap; va_start(ap, kinds);
  double total = 0, scale = 1;
  for (const char *k = kinds; *k; ++k, scale += 1) {
    if (*k == 'i') total += scale * va_arg(ap, int);
    else if (*k == 'l') total += scale * (double)va_arg(ap, long long);
    else if (*k == 'd') total += scale * va_arg(ap, double);
    else if (*k == 'p') total += scale * (double)*va_arg(ap, long long *);
  }
  va_end(ap);
  return -total;
}
long long sum(int count, ...) {
  va_list ap; va_start(ap, count);
  long long total = 0;
  for (int i = 0; i < count; ++i) total = total * 3 + va_arg(ap, long long);
  va_end(ap);
  return total;
}
'''
SOURCE = '''use "std/io"

extern fn mix "mix"(kinds: *const u8, ...) f64
extern fn sum "sum"(count: i32, ...) i64
extern fn mix_again "mix_again"(kinds: *const u8, ...) f64

fn kinds(text: []const u8, buffer: *[32]u8) *const u8 {
  for i in 0..#len(text) {
    buffer.*[i] = text[i]
  }
  buffer.*[#len(text)] = 0
  return &buffer.*[0]
}

fn integers(base: i64) i64 {
  return sum(10, base, base + 1, base + 2, base + 3, base + 4, base + 5, base + 6, base + 7, base + 8, base + 9)
}

fn mixed(x: f64, n: i64) f64 {
  buffer: [32]u8
  cell: i64 = n * 7
  return mix(kinds("dldidpdddddddl", &buffer), x, n, x * 2.0, #cast(i32, n), x * 3.0, &cell, x + 1.0, x + 2.0,
             x + 3.0, x + 4.0, x + 5.0, x + 6.0, x + 7.0, n + 100)
}

fn through(x: f64, n: i64) f64 {
  buffer: [32]u8
  // Chosen at run time, so the call stays indirect.
  f := mix
  if n > 100 {
    f = mix_again
  }
  cell: i64 = n
  return f(kinds("dldidpdddd", &buffer), x, n, x * 2.0, #cast(i32, n), x * 3.0, &cell, x + 1.0, x + 2.0, x + 3.0,
           x + 4.0)
}

fn main() {
  io.println("{} {}", integers(1), integers(-5))
  io.println("{} {}", through(0.5, 3), through(-2.25, 108))
  io.println("{} {}", mixed(0.5, 3), mixed(-1.25, 11))
}
'''
CALLERS = ('integers', 'mixed', 'through')
TARGETS = (('x86_64-linux', ['cc'], []), ('aarch64-linux', ['clang', '--target=aarch64-linux-gnu'], ['qemu-aarch64']),
           ('riscv64-linux', ['clang', '--target=riscv64-linux-gnu', '-march=rv64g', '-mno-relax'], ['qemu-riscv64']),
           ('x86_64-windows', ['zig', 'cc', '-target', 'x86_64-windows-gnu'], ['wine']),
           ('aarch64-macos', ['zig', 'cc', '-target', 'aarch64-macos-none'], None),
           ('x86_64-macos', ['zig', 'cc', '-target', 'x86_64-macos-none'], None),
           ('aarch64-windows', ['zig', 'cc', '-target', 'aarch64-windows-gnu'], None))
with tempfile.TemporaryDirectory(prefix='dyn-ssa-c-variadic-') as temporary:
    work = Path(temporary)
    (work / 'provider.c').write_text(PROVIDER)
    project = work / 'project'
    project.mkdir()
    (project / 'main.dyn').write_text(SOURCE)
    outputs = {}
    for target, cc, emulator in TARGETS:
        if not shutil.which(cc[0]):
            continue
        provider = work / f'{target}.o'
        subprocess.run([*cc, '-std=c11', '-O1', '-ffreestanding', '-fno-sanitize=all', '-fno-stack-protector', '-c',
                        str(work / 'provider.c'), '-o', str(provider)], check=True, timeout=120)
        for name, flags, env in (('ssa', ['--release', '--opt-remarks'], {'DYN_NO_INLINE': '1'}),
                                 ('tree', ['--release'], {'DYN_NO_SSA': '1'}), ('debug', [], {})):
            program = work / f'{target}-{name}{".exe" if "windows" in target else ""}'
            built = subprocess.run([DYN, 'build', str(project), '--target', target, *flags, '--no-cache',
                                    '--link', str(provider), '--output', str(program)],
                                   capture_output=True, text=True, timeout=120, env={**os.environ, **env})
            assert built.returncode == 0, (target, name, built.stderr)
            if name == 'ssa':
                for function in CALLERS:
                    line = [l for l in built.stderr.splitlines() if l.startswith(f'remark: {function}: ')
                            and ('SSA code generation' in l or 'tree emitter' in l)]
                    assert line and 'SSA code generation' in line[0], (target, function, line)
            if emulator is None or (emulator and not shutil.which(emulator[0])):
                continue
            result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=120,
                                    env={**os.environ, 'WINEDEBUG': '-all'})
            assert result.returncode == 0, (target, name, result)
            outputs[(target, name)] = result.stdout.replace('\r\n', '\n')
    reference = outputs[('x86_64-linux', 'tree')]
    for key, output in outputs.items():
        assert output == reference, (key, output, reference)
print('PASS C variadic calls in SSA match the tree emitter; executed:', ', '.join(sorted({t for t, _ in outputs})))
