#!/usr/bin/env python3
"""Execute the arena fixtures shipped to native CI before cross-target staging."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve()

with tempfile.TemporaryDirectory(prefix='dyn-native-arena-fixtures-') as directory:
    for fixture in ('sdk-mem', 'sdk-observe'):
        for mode in ('debug', 'release'):
            output = Path(directory)/(fixture+'-'+mode+('.exe' if os.name == 'nt' else ''))
            subprocess.run([DYN, 'build', ROOT/'tests'/fixture, '--'+mode,
                            '--no-cache', '--quiet', '--output', output],
                           cwd=ROOT, check=True, timeout=120)
            result = subprocess.run([output], capture_output=True, timeout=30)
            assert result.returncode == 0 and not result.stdout and not result.stderr, (
                fixture, mode, result.returncode, result.stdout, result.stderr)
            print('PASS native arena fixture', fixture, mode, flush=True)
