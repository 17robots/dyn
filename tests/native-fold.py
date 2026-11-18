#!/usr/bin/env python3
"""SSA folds keep results and remove work: (b + c) - b is c, so a subslice
xs[b..b + 4] has constant length and its constant indexes compile without
checks; (p << k) * q is (p * q) << k and t + (p << k) one LEA, so
a + b + 2 * x * y costs one multiply; commutative constants move right."""
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-native-fold-') as temporary:
    work = Path(temporary)
    outputs = []
    for flags in (['--debug'], ['--release'], ['--release', '--opt-level', '3']):
        program = work / 'program'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/native-fold'), *flags, '--quiet', '--no-cache', '--output', str(program)],
                       check=True, timeout=180)
        outputs.append(subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=30).stdout)
    assert outputs[0] == outputs[1] == outputs[2], outputs
    if platform.machine() in ('x86_64', 'AMD64'):
        listing = work / 'program.s'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/native-fold'), '--release', '--quiet', '--no-cache', '--emit-asm',
                        '--output', str(listing)], check=True, timeout=180)
        text = (work / 'program.s.s').read_text() if (work / 'program.s.s').exists() else listing.read_text()

        # The helpers inline into main. Before these folds main had 12
        # conditional branches and 11 multiplies; now the window's constant
        # indexes need no checks and the multiply-add one multiply.
        start = text.index('"main":')
        ops = [m.group(1) for m in re.finditer(r'// \+0x[0-9a-f]+: (\w+)', text[start:text.find('\n"', start + 1)])]
        branches = sum(op.startswith('j') and op != 'jmp' for op in ops)
        # Zeroing a local over 256 bytes is a store loop (dec r10d; jne):
        # a back-edge, not a check.
        branches -= sum(ops[i] == 'dec' and ops[i + 1] == 'jne' for i in range(len(ops) - 1))
        assert branches <= 8 and ops.count('imul') <= 9, (branches, ops.count('imul'))
print('PASS native folds: constant-length subslices, multiply-add, commuted constants (debug/release/O3)')
