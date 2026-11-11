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
# Returns pop their frames by the word push returned; deeper than 64 frames
# share one, and the trace keeps the 64 outermost.
DEEP = '''use "std/io"

fn shallow(n: u64) u64 {
  return n + 1
}

fn deep(n: u64, values: []u64) u64 {
  if n == 0 {
    return values[n + 3]
  }
  return deep(n - 1, values) + 1
}

fn main() {
  values: [2]u64 = [1, 2]
  total: u64 = 0
  for i in 0..100 {
    total += shallow(#cast(u64, i))
  }
  io.println("{}", total)
  io.println("{}", deep(70, values[..]))
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-debug-deep-') as directory:
    work = Path(directory)
    main = work / 'main.dyn'
    main.write_text(DEEP)
    for tree in ('0', '1'):
        output = work / ('tree' if tree == '1' else 'ssa')
        built = subprocess.run([DYN, 'build', '--no-cache', str(work), '--output', str(output)],
                               capture_output=True, text=True, timeout=120, env={**os.environ, 'DYN_NO_SSA': tree})
        assert built.returncode == 0, built.stderr
        result = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
        lines = result.stderr.splitlines()
        assert result.returncode == 101 and result.stdout == '5050\n', (tree, result)
        frames = [line for line in lines if line.startswith('  at ')]
        assert len(frames) == 64 and frames[-1] == f'  at main ({main}:21)', (tree, lines)
        assert frames[:-1] == [f'  at deep ({main}:11)'] * 63, (tree, lines)
print('PASS debug panics: located checks, index and length, call lines in traces (SSA and tree)')
