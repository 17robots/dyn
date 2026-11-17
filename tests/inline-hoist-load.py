#!/usr/bin/env python3
"""The O2 inliner hoists pure leaf calls out of a statement. A leaf that reads
a field through a pointer is not pure: hoisting code_of(p) above fail(p) in
println("{} {}", fail(p), code_of(p)) read the old field."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-inline-hoist-load-') as temporary:
    program = Path(temporary) / 'program'
    for flags in (['--debug'], ['--release'], ['--release', '--opt-level', '3']):
        subprocess.run([DYN, 'build', str(ROOT / 'tests/inline-hoist-load'), *flags, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=180)
        output = subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=30).stdout
        assert output == 'false 19\nfalse 57\n', (flags, output)
print('PASS inline hoisting keeps loads through pointers after sibling calls (debug/release/O3)')
