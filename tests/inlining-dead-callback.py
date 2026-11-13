#!/usr/bin/env python3
"""Guarded inlining must not resurrect callbacks with unreconstructed locals."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/fs"
struct Hook { call: fn(isize) }
fn closed(n: isize) {
  file := fs.adopt_handle(n)
  fs.close(&file)
}
fn unused() Hook { return Hook{ call: closed } }
fn invoke(h: Hook, n: isize) {
  if h.call != nil { h.call(n) }
}
fn main() {
  h := Hook{}
  invoke(h, -1)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-dead-callback-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE)
    for level in (2, 3):
        output = work / f'o{level}'
        subprocess.run([DYN, 'build', str(work), '--release', '--opt-level', str(level),
                        '--no-cache', '--output', str(output)], check=True, timeout=120)
        subprocess.run([str(output)], check=True, timeout=30)
print('PASS guarded inlining ignores unreachable callbacks (O2/O3)')
