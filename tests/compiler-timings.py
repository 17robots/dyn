#!/usr/bin/env python3
"""Opt-in phase reporting stays silent by default and covers real build work."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

DYN = str(Path(os.environ.get('DYN', 'build/dyn')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-timing-') as directory:
    root = Path(directory)
    (root/'main.dyn').write_text('fn main() { value: i32 = 42 _ = value }\n')
    for command in ['check', 'build']:
        base = [DYN, command, str(root), '--quiet', '--no-cache', '--no-link', '--output', str(root/'main.o')]
        quiet = subprocess.run(base, capture_output=True, text=True, check=True)
        assert quiet.stderr == '', quiet.stderr
        timed = subprocess.run([*base, '--timings'], capture_output=True, text=True, check=True)
        assert timed.stdout == '', timed.stdout
        phases = {phase: float(duration) for phase, duration in re.findall(r'^timing (.+) ([0-9.]+) ms$', timed.stderr, re.M)}
        expected = {'load', 'detail parse', 'detail ast', 'detail sema'}
        expected |= {'check'} if command == 'check' else {'codegen', 'detail ir', 'detail llvm', 'detail optimize', 'detail emit'}
        assert expected <= phases.keys(), timed.stderr
        assert all(value >= 0 for value in phases.values()), phases
        if command == 'build': assert 'check' not in phases, 'build does semantic checking inside codegen'
print('PASS opt-in compiler phase reporting for check/build')
