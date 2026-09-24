#!/usr/bin/env python3
"""Analyze every compiler C translation unit; warnings and errors fail the gate."""
import concurrent.futures
import os
from pathlib import Path
import shlex
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
flags = shlex.split(os.environ.get('ANALYZER_FLAGS', '--sysroot=/' if sys.platform == 'linux' else ''))
command = [os.environ.get('CLANG', 'clang'), *flags, '--analyze', '-std=c11',
           '-Icompiler/src', '-Itree-sitter-dyn/src', '-Xanalyzer', '-analyzer-output=text']
def check(path):
    result = subprocess.run([*command, str(path)], cwd=ROOT, capture_output=True, text=True)
    output = result.stdout + result.stderr
    return path, result.returncode == 0 and 'warning:' not in output and 'error:' not in output, output
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(check, sorted((ROOT / 'compiler/src').glob('*.c'))))
for path, ok, output in results:
    if output: print(f'{path}:\n{output}', end='')
failed = [str(path) for path, ok, _ in results if not ok]
if failed:
    raise SystemExit('FAIL static analysis: ' + ', '.join(failed))
print(f'PASS static analysis: {len(results)} compiler translation units, no warnings')
