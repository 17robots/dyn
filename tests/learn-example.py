#!/usr/bin/env python3
"""The tour in examples/learn builds, formats cleanly and prints the same output debug and release."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())
TOUR = ROOT / 'examples/learn'
expected = (TOUR / 'expected.txt').read_text()

subprocess.run([DYN, 'fmt', '--check', str(TOUR)], check=True, timeout=60)
with tempfile.TemporaryDirectory(prefix='dyn-learn-') as directory:
    for mode in ([], ['--release']):
        binary = Path(directory) / ('learn-release' if mode else 'learn')
        subprocess.run([DYN, 'build', str(TOUR), *mode, '--quiet', '--no-cache', '--output', str(binary)],
                       check=True, timeout=300)
        run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
        if run.returncode != 0 or run.stdout != expected:
            raise SystemExit(f'FAIL learn tour {mode or "debug"}: exit {run.returncode}\n{run.stdout}{run.stderr}')
print('PASS learn tour: formatted, debug and release output match expected.txt')
