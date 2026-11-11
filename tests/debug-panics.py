#!/usr/bin/env python3
"""Debug panics, with SSA code generation and the tree emitter: the check
message names the statement's file and line and, for an index, the index and
the length; the stack trace names each caller's call line."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())
if platform.system() != 'Linux' or platform.machine() != 'x86_64':
    print('SKIP debug panics: Linux x86-64 execution')
    raise SystemExit(0)
SOURCE = '''use "std/io"
use "std/process"

fn get(values: []i32, at: i64) i32 {
  next := at + 1
  return values[next]
}

fn middle(values: []i32, at: i64) i32 {
  io.println("calling")
  return get(values, at)
}

fn cleaned(values: []i32, at: usize) i32 {
  defer io.println("cleanup")
  return values[at]
}

fn main() {
  program := process.start()
  values: [4]i32 = []
  if #len(program.args) > 1 {
    _ = cleaned(values[..], 6)
  }
  _ = middle(values[..], 8)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-debug-panics-') as directory:
    work = Path(directory)
    main = work / 'main.dyn'
    main.write_text(SOURCE)
    for tree in ('0', '1'):
        output = work / ('tree' if tree == '1' else 'ssa')
        built = subprocess.run([DYN, 'build', '--no-cache', str(work), '--output', str(output)],
                               capture_output=True, text=True, timeout=120, env={**os.environ, 'DYN_NO_SSA': tree})
        assert built.returncode == 0, built.stderr
        result = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 101, result
        lines = result.stderr.splitlines()
        assert lines[0] == f'runtime check failed (index.ok) in get at {main}:6: index 9, length 4', (tree, lines)
        assert lines[1:5] == ['stack trace:', f'  at get ({main}:6)', f'  at middle ({main}:11)',
                              f'  at main ({main}:25)'], (tree, lines)
        # With cleanup pending, SSA code still reports the values.
        result = subprocess.run([str(output), 'x'], capture_output=True, text=True, timeout=30)
        expected = f'runtime check failed (index.ok) in cleaned at {main}:16'
        if tree == '0':
            expected += ': index 6, length 4'
        assert result.stdout == 'cleanup\n' and result.stderr.splitlines()[0] == expected, (tree, result)
print('PASS debug panics: located checks, index and length, call lines in traces (SSA and tree)')
