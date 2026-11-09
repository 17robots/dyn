#!/usr/bin/env python3
"""Four-lane f32 loops match the scalar loop bit for bit: debug builds (no
vectorizer) and -O3 builds print the same results, including NaNs, running
sums, odd counts, nonzero starts, two and three fields per element,
overlapping arrays (which take the scalar loop) and an index past the end,
which still panics after the earlier iterations."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = ROOT / 'tests/vector-loops'
with tempfile.TemporaryDirectory(prefix='dyn-vector-loops-') as directory:
    work = Path(directory)
    results = {}
    for name, flags in (('debug', ['--debug']), ('o2', ['--release']), ('o3', ['--release', '--opt-level', '3'])):
        build = subprocess.run([DYN, 'build', str(SOURCE), *flags, '--no-cache', '--quiet', '--opt-remarks',
                                '--output', str(work / name)], capture_output=True, text=True, timeout=300)
        assert build.returncode == 0, build.stderr
        run = subprocess.run([str(work / name)], capture_output=True, text=True, timeout=60)
        results[name] = (run.returncode, run.stdout, run.stderr.splitlines()[0].split(' at ')[0] if run.stderr else '')
        if name == 'o3' and platform.machine() in ('x86_64', 'AMD64') and os.name != 'nt':
            for function in ('step', 'spin'):
                assert f'remark: {function}: vectorized f32 loop' in build.stderr, build.stderr
    assert results['debug'][0] != 0 and 'index.ok' in results['debug'][2], results['debug']
    assert results['debug'][1].count('\n') == 39, results['debug'][1]
    assert results['o2'] == results['debug'] and results['o3'] == results['debug'], (results['debug'], results['o3'])
print('PASS vector loops: four-lane f32 loops match scalar results bit for bit, overlap and bounds included')
