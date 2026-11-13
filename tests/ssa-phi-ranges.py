#!/usr/bin/env python3
"""Loop phi ranges and loop-exit load reuse.

A probe index masked inside a fixed table, (at + 1) & 1023, stays below the
table length on every iteration, so release builds drop its bounds check, and
the load after the loop reuses the one the loop exit tested. A mask wider than
the table keeps the check, and a probe that runs past the end still fails.
"""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())

SOURCE = '''use "std/io"

table: [1024]u64

fn probe(key: u64) u64 {
  at := #cast(usize, key >> 54)
  for table[at] != 0 && table[at] != key {
    at = (at + 1) & 1023
  }
  if table[at] == key {
    return #cast(u64, at)
  }
  return 9999
}

fn wide(key: u64) u64 {
  at := #cast(usize, key >> 54)
  for table[at] != 0 && table[at] != key {
    at = (at + 1) & 2047
  }
  return #cast(u64, at)
}

// Taken addresses keep both functions out of line for the assembly check.
keep_probe: fn(key: u64) u64 = probe
keep_wide: fn(key: u64) u64 = wide

fn main() {
  table[5] = 77
  table[6] = 5 << 54
  io.println("{} {}", keep_probe(5 << 54), keep_wide(7 << 54))
  table[1023] = 1
  io.println("{}", keep_wide(1023 << 54))
}
'''


def run(*args, env=None):
    return subprocess.run([str(x) for x in args], capture_output=True, text=True, timeout=60, env=env)


with tempfile.TemporaryDirectory(prefix='dyn-phi-ranges-') as directory:
    work = Path(directory)
    source = work / 'src'
    source.mkdir()
    (source / 'main.dyn').write_text(SOURCE)
    for mode, tree in (('--release', '0'), ('--release', '1'), ('--debug', '0')):
        output = work / f'out{mode}{tree}'
        env = dict(os.environ, DYN_NO_SSA=tree)
        built = run(DYN, 'build', source, mode, '--no-cache', '--opt-remarks' if mode == '--release' else '--quiet',
                    '--output', output, env=env)
        assert built.returncode == 0, built.stderr
        ran = run(output)
        # The second wide probe passes the table end: index 1024 must still fail.
        assert ran.returncode != 0 and ran.stdout == '6 7\n', (mode, tree, ran)
        assert 'runtime check failed (index.ok) in wide' in ran.stderr, (mode, tree, ran.stderr)
        # Debug builds name the values.
        assert mode != '--debug' or 'index 1024, length 1024' in ran.stderr, ran.stderr
        if mode != '--release' or tree != '0':
            continue
        assert 'remark: probe: 2 repeated loads reused' in built.stderr, built.stderr
        if platform.system() == 'Linux' and platform.machine() == 'x86_64' and shutil.which('objdump'):
            assembly = subprocess.check_output(['objdump', '-d', '--no-show-raw-insn', str(output)], text=True)
            probe = assembly.split('<probe>:\n')[1].split('\n\n')[0]
            wide = assembly.split('<wide>:\n')[1].split('\n\n')[0]
            assert 'dyn_check_failed' not in probe, ('masked probe kept its bounds check', probe)
            assert 'dyn_check_failed' in wide, ('wider mask lost its bounds check', wide)
print('PASS ssa phi ranges: masked probes, exit load reuse, wide masks checked')
