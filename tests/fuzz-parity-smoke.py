#!/usr/bin/env python3
"""Twenty generated programs print the same in debug, release, opt-level 3
and on the tree code generator (tools/fuzz-parity.py runs more)."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='dyn-fuzz-smoke-') as keep:
    run = subprocess.run([sys.executable, str(ROOT / 'tools/fuzz-parity.py'), '--count', '20', '--seed', '7000',
                          '--keep', keep], capture_output=True, text=True, timeout=1800)
    assert run.returncode == 0, run.stdout + run.stderr
print('PASS fuzz parity: 20 generated programs agree across debug, release, O3 and tree')
