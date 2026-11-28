#!/usr/bin/env python3
"""Every Dyn program under tools/ checks against the current compiler and std,
so an API change cannot leave a tool broken unnoticed."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
directories = sorted({path.parent for path in (ROOT / 'tools').rglob('*.dyn')})
assert directories, 'no Dyn programs under tools/'
failed = []
for directory in directories:
    result = subprocess.run([DYN, 'check', str(directory), '--quiet'], capture_output=True, text=True, timeout=300)
    if result.returncode:
        failed.append((directory.relative_to(ROOT), result.stderr.strip()[:400]))
assert not failed, failed
print(f'PASS tools check: {len(directories)} Dyn programs under tools/')
