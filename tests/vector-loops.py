#!/usr/bin/env python3
"""f32, f64 and i32 lane loops match the scalar loop bit for bit: debug builds (no
vectorizer) and -O3 builds print the same results, including NaNs, running
sums, odd counts, nonzero starts, two and three fields per element,
overlapping arrays (which take the scalar loop) and an index past the end,
which still panics after the earlier iterations."""
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = ROOT / 'tests/vector-loops'
with tempfile.TemporaryDirectory(prefix='dyn-vector-loops-') as directory:
    work = Path(directory)
    results = {}
    for name, flags in (('debug', ['--debug', '--no-check-overflow']), ('o2', ['--release']), ('o3', ['--release', '--opt-level', '3']),
                        ('native', ['--release', '--opt-level', '3', '--cpu', 'native'])):
        build = subprocess.run([DYN, 'build', str(SOURCE), *flags, '--no-cache', '--quiet', '--opt-remarks',
                                '--output', str(work / name)], capture_output=True, text=True, timeout=300)
        assert build.returncode == 0, build.stderr
        run = subprocess.run([str(work / name)], capture_output=True, text=True, timeout=60)
        results[name] = (run.returncode, run.stdout, run.stderr.splitlines()[0].split(' at ')[0] if run.stderr else '')
        if name == 'o3' and platform.machine() in ('x86_64', 'AMD64') and os.name != 'nt':
            for function in ('step', 'spin', 'drift', 'twist', 'scale', 'blend'):
                assert re.search(f'remark: {function}: vectorized [fi](32|64) loop', build.stderr), (function, build.stderr)
    assert results['debug'][0] != 0 and 'index.ok' in results['debug'][2], results['debug']
    assert results['debug'][1].count('\n') == 53, results['debug'][1]
    for name in ('o2', 'o3', 'native'):
        assert results[name] == results['debug'], (name, results['debug'], results[name])
    # AArch64 runs the same programs under QEMU when it is installed.
    if shutil.which('qemu-aarch64'):
        arm = {}
        for name, flags in (('debug', ['--debug', '--no-check-overflow']), ('o3', ['--release', '--opt-level', '3'])):
            build = subprocess.run([DYN, 'build', str(SOURCE), '--target', 'aarch64-linux', *flags, '--no-cache', '--quiet',
                                    '--opt-remarks', '--output', str(work / ('arm-' + name))], capture_output=True, text=True, timeout=300)
            assert build.returncode == 0, build.stderr
            if name == 'o3':
                for function in ('step', 'spin', 'drift', 'twist', 'scale', 'blend', 'churn'):
                    assert re.search(f'remark: {function}: vectorized [fi](32|64) loop', build.stderr), (function, build.stderr)
            run = subprocess.run(['qemu-aarch64', str(work / ('arm-' + name))], capture_output=True, text=True, timeout=120)
            arm[name] = (run.returncode, run.stdout)
        # Generated NaNs differ by architecture (x86 sets the sign bit), so
        # AArch64 is compared with itself.
        assert arm['o3'] == arm['debug'] and arm['debug'][1].count('\n') == 53, arm
    else:
        print('SKIP vector loops on AArch64: qemu-aarch64 unavailable')
print('PASS vector loops: f32, f64 and i32 lane loops match scalar results bit for bit, overlap and bounds included')
