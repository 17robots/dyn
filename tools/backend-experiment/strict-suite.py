#!/usr/bin/env python3
"""Run tests/run.py's scripts through strict-dyn.py, reporting every failure.

Tests that copy or relocate the compiler executable into an SDK layout cannot
use a wrapper script and are omitted; the ordinary suite covers them.
"""
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RELOCATING = {'runtime-audit', 'vendor-bindings', 'release-bundle', 'scale-benchmark'}
names = []
for name in re.findall(r"([a-z0-9-]+)\.py", (ROOT/'tests/run.py').read_text()):
    if name not in names and name not in RELOCATING and (ROOT/'tests'/f'{name}.py').exists() and name != 'run':
        names.append(name)
env = dict(os.environ, DYN=str(ROOT/'tools/backend-experiment/strict-dyn.py'))
failed = []
for name in names:
    result = subprocess.run([sys.executable, ROOT/'tests'/f'{name}.py'], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=900)
    if result.returncode:
        failed.append(name)
        print(f'FAIL {name}\n{result.stdout[-2000:]}{result.stderr[-4000:]}')
if failed:
    sys.exit(f'native strict failures: {", ".join(failed)}')
print(f'PASS native strict suite: {len(names)} scripts')
