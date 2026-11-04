#!/usr/bin/env python3
"""dyn vet reports unused locals; --unsafe lists unsafe operations."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
module = str(ROOT / 'tests/vet-checks')
plain = subprocess.run([DYN, 'vet', module], capture_output=True, text=True, timeout=60)
assert plain.returncode == 1 and 'local is never used' in plain.stderr and 'unsafe:' not in plain.stderr, plain
full = subprocess.run([DYN, 'vet', '--unsafe', module], capture_output=True, text=True, timeout=60)
for message in ('unsafe: #slice', 'unsafe: #offset', 'unsafe: pointer cast'):
    assert message in full.stderr, (message, full.stderr)
print('PASS vet: unused locals and the unsafe report')
