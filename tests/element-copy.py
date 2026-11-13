#!/usr/bin/env python3
"""Element copy loops, as in mem.copy, become one copy in x86-64 release
builds: every length from 0 to 100, overlap either way, wider elements, and a
short destination that must still fail at its first missing index give the
results of the ordinary loop."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
EXPECTED = '14394786373240357554\n'
with tempfile.TemporaryDirectory(prefix='dyn-element-copy-') as temporary:
    for name, flags in (('debug', ['--debug']), ('release', ['--release']), ('o3', ['--release', '--opt-level', '3'])):
        program = Path(temporary) / name
        built = subprocess.run([DYN, 'build', str(ROOT / 'tests/element-copy'), *flags, '--opt-remarks', '--no-cache',
                                '--output', str(program)], capture_output=True, text=True, timeout=120)
        assert built.returncode == 0, built.stderr
        if name != 'debug' and platform.machine() == 'x86_64':
            assert built.stderr.count('element copy loop became one copy') >= 2, built.stderr
        result = subprocess.run([str(program)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0 and result.stdout == EXPECTED, (name, result)
        failed = subprocess.run([str(program), 'short'], capture_output=True, text=True, timeout=60)
        assert failed.returncode == 101 and 'runtime check failed (index.ok) in copy_bytes' in failed.stderr, (name, failed)
        if name == 'debug':
            assert 'index 10, length 10' in failed.stderr and '  at copy_bytes (' in failed.stderr, failed.stderr
print('PASS element copy loops')
