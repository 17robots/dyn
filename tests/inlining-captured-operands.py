#!/usr/bin/env python3
"""A call right of an operand it may change still inlines: the operand is read first, as before."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"

counter: i64

fn bump(by: i64) i64 {
  counter += by
  return by
}

fn main() {
  counter = 1
  a := counter + bump(10)
  b := counter * (counter - bump(1))
  total: i64 = 0
  for i in 0..1000 {
    total += counter - bump(i)
  }
  io.println("{} {} {} {}", a, b, total, counter)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-captured-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE)
    for name, flags in (('debug', ['--debug']), ('o2', ['--release', '--opt-level', '2']),
                        ('o3', ['--release', '--opt-level', '3'])):
        program = work / name
        subprocess.run([DYN, 'build', str(work), *flags, '--quiet', '--no-cache', '--output', str(program)],
                       check=True, timeout=120)
        result = subprocess.run([str(program)], capture_output=True, text=True, timeout=30, check=True)
        assert result.stdout == '11 110 165679500 499512\n', (name, result.stdout)
    if os.uname().machine == 'x86_64':
        asm = subprocess.run(['objdump', '-d', str(work / 'o3')], capture_output=True, text=True, check=True).stdout
        body = re.search(r'<main>:\n(.*?)(?=\n\n|\Z)', asm, re.S)
        assert body and not re.search(r'call.*<bump>', body[1]), 'bump stayed a call'
print('PASS captured operands: order kept, call inlined (debug/O2/O3)')
