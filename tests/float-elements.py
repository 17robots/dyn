#!/usr/bin/env python3
"""Vectorized float element loops keep scalar results, overlap and panic behavior."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
OUT_OF_RANGE = '''fn f(c: []f64, b: []f64, v: f64, n: usize) {
  for j in 0..n {
    c[j] += v * b[j]
  }
}
extern fn write(fd: i32, data: *const u8, count: usize) isize
fn main() {
  c: [6]f64
  b: [4]f64
  b[0] = 1.0
  f(c[0..6], b[0..4], 2.0, 6)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-float-elements-') as temporary:
    root = Path(temporary)
    for name, flags in (('debug', ['--debug']), ('release', ['--release']), ('vector', ['--release', '--opt-level', '3', '--opt-remarks'])):
        program = root / name
        run = subprocess.run([DYN, 'build', str(ROOT / 'tests/float-elements'), *flags, '--no-cache', '--quiet',
                              '--output', str(program)], capture_output=True, text=True, timeout=120)
        assert run.returncode == 0, run.stdout + run.stderr
        if name == 'vector':
            assert 'vectorized float element loop' in run.stdout + run.stderr, run.stdout + run.stderr
        subprocess.run([str(program)], check=True, timeout=30)
    project = root / 'bounds'
    project.mkdir()
    (project / 'main.dyn').write_text(OUT_OF_RANGE.replace('extern fn write(fd: i32, data: *const u8, count: usize) isize\n', ''))
    program = root / 'bounds-program'
    subprocess.run([DYN, 'build', str(project), '--release', '--opt-level', '3', '--quiet', '--no-cache', '--output', str(program)],
                   check=True, timeout=120)
    result = subprocess.run([str(program)], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'index.ok' in result.stderr, (result.returncode, result.stderr)
print('PASS float element loops')
