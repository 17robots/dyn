#!/usr/bin/env python3
"""Release kernels against time budgets. Budgets are about 3x a Ryzen 9 9950X run,
so they catch a lost optimization rather than noise. Run on a quiet machine."""
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
BUDGETS = {'nbody': 3.0, 'sum': 6.5, 'matmul': 1.5, 'structs': 2.8, 'pairs': 2.0, 'map-small': 0.5, 'map-large': 2.8}
failed = []
with tempfile.TemporaryDirectory(prefix='dyn-kernels-') as temporary:
    for name, budget in BUDGETS.items():
        program = Path(temporary) / name
        subprocess.run([DYN, 'build', str(ROOT / 'tests/kernels' / name), '--release', '--opt-level', '3',
                        '--quiet', '--no-cache', '--output', str(program)], check=True, timeout=60)
        started = time.time()
        subprocess.run([str(program)], check=True, timeout=120, stdout=subprocess.DEVNULL)
        elapsed = time.time() - started
        print(f'{name}: {elapsed:.3f}s (budget {budget}s)')
        if elapsed > budget:
            failed.append(name)
assert not failed, failed
print('PASS release kernels within budget')
