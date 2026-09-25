#!/usr/bin/env python3
"""Debugger locations must refer to original files, not merged module lines."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
if not shutil.which('gdb'):
    raise SystemExit('gdb required for multi-file debug regression')
with tempfile.TemporaryDirectory(prefix='dyn-debug-files-') as folder:
    root = Path(folder)
    helper = root / 'helper.dyn'
    helper.write_text('fn compute(seed: i64) i64 {\n  value := seed + 2\n  return value\n}\nstruct Pair { value: i64 }\ncounter: Pair = Pair{ value: 7 }\n')
    (root / 'main.dyn').write_text('fn main() {\n  answer := compute(19)\n  _ = answer\n  _ = counter\n}\n')
    output = root / 'program'
    subprocess.run([os.environ.get('DYN', './build/dyn'), 'build', folder, '--debug', '--no-cache', '--quiet', '--output', str(output)], check=True)
    result = subprocess.run(['gdb', '-q', '-nx', '-batch', '-ex', 'set debuginfod enabled off',
        '-ex', f'break {helper}:3', '-ex', 'run', '-ex', 'print value', '-ex', 'bt', '-ex', 'info variables counter', '-ex', 'info types Pair', str(output)], capture_output=True, text=True)
    assert '$1 = 21' in result.stdout, result.stdout + result.stderr
    assert f'{helper}:3' in result.stdout, result.stdout
    assert f'{root / "main.dyn"}:2' in result.stdout, result.stdout
    assert result.stdout.count(f'File {helper}:') >= 2, result.stdout + result.stderr
