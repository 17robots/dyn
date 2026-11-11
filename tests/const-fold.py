#!/usr/bin/env python3
"""Release builds fold constant globals, including shifts, and inline leaves that read them."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"
const Bits: u64 = 23
const Capacity: usize = 1 << 23
const Negative: i64 = -64 >> 3
const High: u64 = 0xff00000000000000 >> 56
const Signed: i32 = -1 << 4
const Limit: u32 = 7
fn slot(key: u64) usize {
  return #cast(usize, ((key * 11400714819323198485) >> (64 - Bits)))
}
fn read(p: *const u32) u32 {
  return p.*
}
fn main() {
  total: usize = 0
  for i in 0..1000 {
    total += slot(#cast(u64, i)) & (Capacity - 1)
  }
  io.println("{} {} {} {} {} {}", total, Capacity, Negative, High, Signed, read(&Limit))
}
'''


def main():
    expected = None
    with tempfile.TemporaryDirectory(prefix='dyn-const-fold-') as temporary:
        project = Path(temporary)
        (project / 'main.dyn').write_text(SOURCE)
        for release in (False, True):
            output = project / ('release' if release else 'debug')
            build = subprocess.run([DYN, 'build', str(project), '--no-cache', '--output', str(output),
                                    *(['--release', '--opt-remarks'] if release else ['--quiet'])],
                                   capture_output=True, text=True, timeout=90)
            assert build.returncode == 0, build.stdout + build.stderr
            if release:
                inlined = re.search(r'remark: (\d+) direct calls inlined', build.stderr)
                assert inlined and int(inlined.group(1)) >= 1, build.stderr
                remark = re.search(r'remark: main: SSA code generation, (\d+) spill slots', build.stderr)
                assert remark, build.stderr
            run = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
            assert run.returncode == 0, run.stderr
            if expected is None:
                expected = run.stdout
            assert run.stdout == expected, (run.stdout, expected)
    fields = expected.split()
    assert fields[1:] == ['8388608', '-8', '255', '-16', '7'], expected
    print('PASS constant globals fold in release, leaves reading them inline, addresses stay')


if __name__ == '__main__':
    main()
