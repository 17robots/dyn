#!/usr/bin/env python3
"""thread.cpu_count matches the affinity mask on Linux and builds for every hosted target."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = ROOT / 'tests/thread-cpu-count'
with tempfile.TemporaryDirectory(prefix='dyn-cpu-count-') as temporary:
    for target in ('aarch64-linux', 'riscv64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows'):
        subprocess.run([DYN, 'build', str(SOURCE), '--target', target, '--quiet', '--no-cache',
                        '--output', str(Path(temporary) / f'cpu-{target}')], check=True, timeout=120)
    if sys.platform == 'linux':
        program = Path(temporary) / 'cpu'
        subprocess.run([DYN, 'build', str(SOURCE), '--quiet', '--no-cache', '--output', str(program)], check=True, timeout=120)
        expected = len(os.sched_getaffinity(0))
        assert subprocess.run([str(program)], capture_output=True, text=True, check=True).stdout == f'{expected}\n'
        if shutil.which('taskset') and expected > 1:
            pinned = subprocess.run(['taskset', '-c', '0', str(program)], capture_output=True, text=True, check=True).stdout
            assert pinned == '1\n', pinned
print('PASS thread.cpu_count: affinity mask, taskset pinning, cross-builds')
