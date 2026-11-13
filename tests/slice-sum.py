#!/usr/bin/env python3
"""Vectorized slice sums match scalar results at every length and width."""
import os
import shutil
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-slice-sum-') as temporary:
    root = Path(temporary)
    for name, flags in (('debug', ['--debug', '--no-check-overflow']), ('release', ['--release']), ('vector', ['--release', '--opt-level', '3', '--opt-remarks'])):
        program = root / name
        run = subprocess.run([DYN, 'build', str(ROOT / 'tests/slice-sum'), *flags, '--no-cache', '--quiet',
                              '--output', str(program)], capture_output=True, text=True, timeout=120)
        assert run.returncode == 0, run.stdout + run.stderr
        if name == 'vector':
            assert 'vectorized slice sum' in run.stdout + run.stderr, run.stdout + run.stderr
        subprocess.run([str(program)], check=True, timeout=30)
    for test, target, emulator in (('slice-sum', 'aarch64-linux', 'qemu-aarch64'), ('float-elements', 'aarch64-linux', 'qemu-aarch64')):
        program = root / (test + target)
        run = subprocess.run([DYN, 'build', str(ROOT / 'tests' / test), '--target', target, '--release', '--opt-level', '3',
                              '--opt-remarks', '--no-cache', '--quiet', '--output', str(program)], capture_output=True, text=True, timeout=120)
        assert run.returncode == 0 and 'vectorized' in run.stdout + run.stderr, run.stdout + run.stderr
        if shutil.which(emulator):
            subprocess.run([emulator, str(program)], check=True, timeout=60)
    project = root / 'bounds'
    project.mkdir()
    (project / 'main.dyn').write_text('fn f(xs: []i32, n: usize) i32 {\n  t: i32 = 0\n  for i in 0..n {\n    t += xs[i]\n  }\n  return t\n}\n'
                                      'fn main() {\n  a: [3]i32\n  _ = f(a[0..3], 4)\n}\n')
    program = root / 'bounds-program'
    subprocess.run([DYN, 'build', str(project), '--release', '--opt-level', '3', '--quiet', '--no-cache', '--output', str(program)], check=True, timeout=120)
    result = subprocess.run([str(program)], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'index.ok' in result.stderr, (result.returncode, result.stderr)
print('PASS slice sums')
