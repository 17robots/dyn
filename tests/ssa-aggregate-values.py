#!/usr/bin/env python3
"""Arrays and payload enums passed and returned by value stay in SSA code.

SSA once gave up on any function that took or returned a fixed array or a
payload enum by value, sending tagged-enum code such as `fn area(s: Shape)`
to the tree emitter. SSA now passes them leaf by leaf, as the tree emitter
does, and returns them through memory or, on x86-64 System V, in RAX/RDX and
XMM0/XMM1. Results that need RCX or x87 (three integer leaves, more than two
float leaves) still use the tree emitter, which exercises SSA callers of tree
callees and the reverse, including leaves passed on the stack. Every build
must print what the tree emitter alone prints (DYN_NO_SSA=1)."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = ROOT / 'tests/ssa-aggregate-values'
EXPECTED = '0.5 2.5 21 40 \n7 21 42\n55 244 39\n69 259 54\n100 274 78\n131 289 96\n1533 2946\n152.5\n'
# x86-64 System V: these must be SSA; widen, sum_ints, via_tree and tree_take
# return or call three-integer results and stay on the tree emitter.
SSA_FUNCTIONS = ('make', 'measure', 'wide_value', 'sum_floats', 'mixed', 'ssa_call')
with tempfile.TemporaryDirectory(prefix='dyn-ssa-aggregate-values-') as temporary:
    for target, emulator in (('x86_64-linux', []), ('aarch64-linux', ['qemu-aarch64']),
                             ('riscv64-linux', ['qemu-riscv64']), ('x86_64-windows', ['wine'])):
        for name, flags, env in (('tree', ['--release'], {'DYN_NO_SSA': '1'}),
                                 ('ssa', ['--release', '--opt-remarks'], {'DYN_NO_INLINE': '1'}),
                                 ('inlined', ['--release'], {}), ('debug', [], {})):
            program = Path(temporary) / f'{target}-{name}{".exe" if "windows" in target else ""}'
            built = subprocess.run([DYN, 'build', str(SOURCE), '--target', target, *flags, '--no-cache',
                                    '--output', str(program)], capture_output=True, text=True, timeout=120,
                                   env={**os.environ, **env})
            assert built.returncode == 0, (target, name, built.stderr)
            if name == 'ssa':
                remarks = [l for l in built.stderr.splitlines() if 'SSA code generation' in l or 'tree emitter' in l]
                for function in SSA_FUNCTIONS:
                    line = [l for l in remarks if l.startswith(f'remark: {function}: ')]
                    assert line and 'SSA code generation' in line[0], (target, function, line)
                if target != 'x86_64-linux' and target != 'x86_64-windows':
                    assert not any('tree emitter' in l for l in remarks), (target, remarks)
            if emulator and not shutil.which(emulator[0]):
                continue
            result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=120,
                                    env={**os.environ, 'WINEDEBUG': '-all'})
            assert result.returncode == 0 and result.stdout.replace('\r\n', '\n') == EXPECTED, (target, name, result)
print('PASS arrays and payload enums by value in SSA; stack leaves and mixed SSA/tree calls match')
