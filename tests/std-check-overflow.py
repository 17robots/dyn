#!/usr/bin/env python3
"""Std's own arithmetic passes --check-overflow: programs that drive hashing,
crypto, compression, JSON, HTTP and maps run clean with checks on, so code
that means to wrap is written inside #wrapping."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
if platform.system() != 'Linux' or platform.machine() != 'x86_64':
    print('SKIP std check overflow: Linux x86-64 execution')
    raise SystemExit(0)
PROGRAMS = (('argon2-results', ['rfc']), ('http-helpers', []), ('web-batteries', []), ('hpack', []),
            ('container-map', []), ('sha256-hardware', []), ('sqlite-helpers', []), ('parse-integers', []))
with tempfile.TemporaryDirectory(prefix='dyn-std-check-overflow-') as directory:
    for name, arguments in PROGRAMS:
        project = ROOT / 'tests' / name
        if not project.is_dir():
            continue
        for mode in ('--debug', '--release'):
            program = Path(directory) / f'{name}{mode}'
            subprocess.run([DYN, 'build', str(project), mode, '--check-overflow', '--quiet', '--no-cache',
                            '--output', str(program)], check=True, timeout=300)
            result = subprocess.run([str(program), *arguments], capture_output=True, text=True, timeout=120,
                                    cwd=project)
            assert 'overflow.ok' not in result.stderr, (name, mode, result.stderr[-600:])
            assert result.returncode == 0, (name, mode, result.returncode, result.stderr[-600:])
print('PASS std under --check-overflow: hashing, crypto, compression, JSON, HTTP, maps (debug/release)')
