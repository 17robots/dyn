#!/usr/bin/env python3
"""Recursive inlining after accumulator recursion.

ssa_accumulate turns `return f(a) + f(b)` into a loop with one call left;
ssa_self_inline then copies that loop into its own call site a few levels
deep. The program covers Fibonacci in i64 and in wrapping u64, a function of
two parameters whose arguments differ per call, a function with two base
returns (so each copy's returns meet in a phi), and a function whose call
is not the recursion's tail (no copy). Release builds report the inlining
with --opt-remarks, and every build prints what the tree emitter prints."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"

fn fib(n: i64) i64 {
  if n < 2 {
    return n
  }
  return fib(n - 1) + fib(n - 2)
}

fn wide(n: u64) u64 {
  if n < 2 {
    return n * 18446744073709551557
  }
  return wide(n - 1) + wide(n - 2)
}

fn paths(n: i64, k: i64) i64 {
  if n < 2 {
    return k
  }
  return paths(n - 1, k + 1) + paths(n - 2, k * 3 - n)
}

fn two(n: u64) u64 {
  if n == 0 {
    return 7
  }
  if n == 1 {
    return 11
  }
  return two(n - 1) + two(n - 2)
}

fn scaled(n: i64) i64 {
  if n < 2 {
    return n
  }
  return scaled(n - 1) * 3 + scaled(n - 2)
}

fn main() {
  io.println("{} {} {} {} {}", fib(27), wide(30), paths(20, 1), two(30), scaled(16))
}
'''
INLINED = ('fib', 'wide', 'paths', 'two')
with tempfile.TemporaryDirectory(prefix='dyn-ssa-self-inline-') as temporary:
    source = Path(temporary) / 'main.dyn'
    source.write_text(SOURCE)
    expected = None
    for target, emulator in (('x86_64-linux', []), ('aarch64-linux', ['qemu-aarch64']),
                              ('riscv64-linux', ['qemu-riscv64']), ('x86_64-windows', ['wine'])):
        for name, env in (('tree', {'DYN_NO_SSA': '1'}), ('ssa', {})):
            program = Path(temporary) / f'{target}-{name}{".exe" if "windows" in target else ""}'
            built = subprocess.run([DYN, 'build', str(source), '--release', '--target', target, '--no-cache', '--quiet',
                                    '--opt-remarks', '--output', str(program)], capture_output=True, text=True, check=True,
                                   timeout=120, env={**os.environ, **env})
            if name == 'ssa':
                for function in (*INLINED, 'scaled'):
                    remark = f'remark: {function}: recursive call inlined'
                    assert (remark in built.stderr) == (function in INLINED), (target, function, built.stderr)
            if emulator and not shutil.which(emulator[0]):
                continue
            result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=60,
                                    env={**os.environ, 'WINEDEBUG': '-all'})
            assert result.returncode == 0, (target, name, result)
            output = result.stdout.replace('\r\n', '\n')
            expected = expected or output
            assert output == expected, (target, name, output, expected)
print('PASS self inline: accumulated recursion inlines into itself; outputs match the tree emitter on every target')
