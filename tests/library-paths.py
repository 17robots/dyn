#!/usr/bin/env python3
"""A project whose path merely contains /std/ or /vendor/ is the program's own
code: --check-overflow covers it. Only the SDK's std and vendor trees wrap."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/hash"
use "std/io"

fn main() {
  io.println("{}", hash.hash64("library code wraps"))
  x: i32 = 2147483600
  for i in 0..100 { x += 1 }
  io.println("{}", x)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-library-paths-') as temporary:
    for directory in ('vendor/app', 'std/app', 'share/dyn/app'):
        project = Path(temporary) / directory
        project.mkdir(parents=True)
        (project / 'main.dyn').write_text(SOURCE)
        program = project / 'program'
        subprocess.run([DYN, 'build', str(project), '--debug', '--check-overflow', '--quiet', '--no-cache', '--output', str(program)],
                       check=True, timeout=180)
        run = subprocess.run([str(program)], capture_output=True, text=True, timeout=30)
        assert run.returncode == 101 and 'overflow.ok' in run.stderr, (directory, run.returncode, run.stdout, run.stderr)
        assert run.stdout.count('\n') == 1, (directory, run.stdout)
print('PASS library paths: only the SDK std and vendor trees skip --check-overflow')
