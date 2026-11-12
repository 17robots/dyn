#!/usr/bin/env python3
"""Arrays and payload enums passed and returned by value compile to SSA code.

SSA once gave up on any function that took or returned a fixed array or a
payload enum by value, sending tagged-enum code such as `fn area(s: Shape)`
to the tree emitter. SSA now passes them leaf by leaf, as the tree emitter
does, and returns them through memory or, on x86-64 System V, in RAX, RDX,
RCX, XMM0, XMM1 and the x87 stack. DYN_TREE_FUNCTIONS keeps chosen functions
on the tree emitter, so calls between the emitters are checked in both
directions, including leaves passed on the stack and x87 results. Every
build must print what the tree emitter alone prints (DYN_NO_SSA=1)."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = ROOT / 'tests/ssa-aggregate-values'
EXPECTED = '0.5 2.5 21 40 \n7 21 42\n55 244 39\n69 259 54\n100 274 78\n131 289 96\n1533 2946\n33 99\n152.5\n'
FUNCTIONS = ('make', 'measure', 'widen', 'wide_value', 'sum_ints', 'sum_floats', 'mixed', 'via_tree',
             'tree_take', 'ssa_call', 'corners', 'corner_sum', 'main')
# Two splits between the emitters: each half calls the other.
SPLITS = (('widen', 'sum_ints', 'via_tree', 'tree_take', 'corners', 'main'),
          ('make', 'measure', 'wide_value', 'sum_floats', 'mixed', 'ssa_call', 'corner_sum'))


def remarks(stderr):
    found = {}
    for line in stderr.splitlines():
        for function in FUNCTIONS:
            if line.startswith(f'remark: {function}: ') and ('SSA code generation' in line or 'tree emitter' in line):
                found[function] = 'SSA code generation' in line
    return found


with tempfile.TemporaryDirectory(prefix='dyn-ssa-aggregate-values-') as temporary:
    for target, emulator in (('x86_64-linux', []), ('aarch64-linux', ['qemu-aarch64']),
                             ('riscv64-linux', ['qemu-riscv64']), ('x86_64-windows', ['wine'])):
        configurations = [('tree', ['--release'], {'DYN_NO_SSA': '1'}, None),
                          ('ssa', ['--release', '--opt-remarks'], {'DYN_NO_INLINE': '1'}, ()),
                          ('inlined', ['--release'], {}, None), ('debug', [], {}, None)]
        configurations += [(f'split{i}', ['--release', '--opt-remarks'],
                            {'DYN_NO_INLINE': '1', 'DYN_TREE_FUNCTIONS': ','.join(split)}, split)
                           for i, split in enumerate(SPLITS)]
        for name, flags, env, tree in configurations:
            program = Path(temporary) / f'{target}-{name}{".exe" if "windows" in target else ""}'
            built = subprocess.run([DYN, 'build', str(SOURCE), '--target', target, *flags, '--no-cache',
                                    '--output', str(program)], capture_output=True, text=True, timeout=120,
                                   env={**os.environ, **env})
            assert built.returncode == 0, (target, name, built.stderr)
            if tree is not None:
                found = remarks(built.stderr)
                for function in FUNCTIONS:
                    assert found.get(function) == (function not in tree), (target, name, function, found)
            if emulator and not shutil.which(emulator[0]):
                continue
            result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=120,
                                    env={**os.environ, 'WINEDEBUG': '-all'})
            assert result.returncode == 0 and result.stdout.replace('\r\n', '\n') == EXPECTED, (target, name, result)
print('PASS arrays and payload enums by value in SSA on every 64-bit target; mixed SSA/tree calls match')
