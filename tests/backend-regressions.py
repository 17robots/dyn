#!/usr/bin/env python3
"""Backend safety checks, expression evaluation, strings, and guard scaling."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())


CASES = {
    'range': (r'''fn main() {
  value: u64 = 0
  if true { value = 18446744073709551615 }
  i: usize = 0
  for i < 1 {
    value += 1
    i += 1
  }
  if value == 0 { #panic("WRAPPED") }
}
''', 'overflow.ok'),
    'range_isize_overflow': (r'''fn main() {
  value: isize = 9223372036854775806
  i: usize = 0
  for i < 2 {
    value += 1
    i += 1
  }
  #panic("SIGNED WRAPPED")
}
''', 'overflow.ok'),
    'bounds': (r'''fn main() {
  values := [10, 20, 30]
  index: usize = 0
  i: usize = 0
  for i < 1 {
    index = 100
    _ = values[index]
    i += 1
  }
  #panic("BOUNDS CHECK SKIPPED")
}
''', 'index.ok'),
    'compound': (r'''calls: usize = 0
fn next() usize {
  calls += 1
  return calls - 1
}
fn main() {
  values := [10, 20, 30]
  values[next()] += 1
  if values[0] != 11 || values[1] != 20 { #panic("WRONG TARGET UPDATED") }
  if calls != 1 { #panic("TARGET CALLED TWICE") }
}
''', None),
    'nan': (r'''fn main() {
  zero: f64 = 0.0
  nan := zero / zero
  if !(nan != nan) { #panic("NAN UNEQUAL IS FALSE") }
}
''', None),
    'range_multiple_writes': (r'''fn main() {
  value: u8 = 0
  i: usize = 0
  for i < 1 {
    value += 200
    value += 100
    i += 1
  }
  #panic("WRAPPED")
}
''', 'overflow.ok'),
    'range_mutated_step': (r'''fn main() {
  value: u8 = 0
  step: u8 = 1
  i: usize = 0
  for i < 2 {
    step = 200
    value += step
    i += 1
  }
  #panic("WRAPPED")
}
''', 'overflow.ok'),
    'range_mutated_bound': (r'''fn main() {
  value: u8 = 0
  end: usize = 1
  i: usize = 0
  for i < end {
    end = 3
    value += 100
    i += 1
  }
  #panic("WRAPPED")
}
''', 'overflow.ok'),
    'range_later_function': (r'''fn earlier() u64 {
  a: u64 = 11
  b: u64 = 22
  return a + b
}
fn sum() u64 {
  values: [3]u64 = [10, 20, 30]
  total: u64 = 0
  i: usize = 0
  for i < 3 {
    total += values[i]
    i += 1
  }
  return total
}
fn main() {
  if earlier() != 33 || sum() != 60 { #panic("FUNCTION LOCAL RANGE") }
}
''', None),
    'range_later_function_mutation': (r'''fn earlier() u64 {
  a: u64 = 11
  b: u64 = 22
  return a + b
}
fn overflow() {
  value: u8 = 0
  if true { value = 255 }
  i: usize = 0
  for i < 1 {
    value += 1
    i += 1
  }
  #panic("LATER FUNCTION WRAPPED")
}
fn main() {
  _ = earlier()
  overflow()
}
''', 'overflow.ok'),
    'guard_branch': (r'''fn probe(values: []i64, index: usize, first: bool) {
  if first { _ = values[index] }
  _ = values[index]
}
fn main() {
  values: [3]i64 = [10, 20, 30]
  probe(values[..], 100, false)
  #panic("BRANCH CHECK SKIPPED")
}
''', 'index.ok'),
    'string_bytes': (r'''stored := "a\0é"
empty := ""
fn main() {
  local := "b\0é"
  blank := ""
  if #len(stored) != 4 || stored[0] != 97 || stored[1] != 0 || stored[2] != 195 || stored[3] != 169 { #panic("STATIC STRING BYTES") }
  if #len(local) != 4 || local[0] != 98 || local[1] != 0 || local[2] != 195 || local[3] != 169 { #panic("LOCAL STRING BYTES") }
  if #len(empty) != 0 || #len(blank) != 0 { #panic("EMPTY STRING") }
}
''', None),
}


def build(directory, output, *options):
    result = subprocess.run(
        [DYN, 'build', str(directory), '--no-cache', '--jobs', '1',
         '--output', str(output), *options],
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, (directory.name, options, result.stderr)


with tempfile.TemporaryDirectory(prefix='dyn-backend-regressions-') as temporary:
    root = Path(temporary)
    for name, (source, expected_error) in CASES.items():
        directory = root / name
        directory.mkdir()
        (directory / 'main.dyn').write_text(source)
        for release in (False, True):
            output = directory / ('release' if release else 'debug')
            build(directory, output, *(['--release'] if release else []))
            result = subprocess.run([str(output)], capture_output=True,
                                    text=True, timeout=10)
            diagnostic = result.stdout + result.stderr
            if expected_error:
                assert result.returncode != 0 and expected_error in diagnostic, (
                    name, release, result.returncode, diagnostic)
            else:
                assert result.returncode == 0, (name, release, diagnostic)

    # usize must use the target width rather than the host's 64-bit width.
    # Emit unoptimized IR so the assertion checks the compiler's proof itself.
    directory = root / 'range-usize-wasm32'
    directory.mkdir()
    (directory / 'main.dyn').write_text('''fn main() {
  value: usize = 4294967294
  i: usize = 0
  for i < 2 {
    value += 1
    i += 1
  }
  #panic("UNSIGNED WRAPPED")
}
''')
    output = directory / 'wasm32'
    build(directory, output, '--target', 'wasm32-wasi', '--emit-ir', '--no-link')
    ir = output.with_suffix('.ll').read_text()
    assert 'call { i32, i1 } @llvm.uadd.with.overflow.i32' in ir, ir

    # Exercise thousands of guard pairs without comparing wall-clock timings.
    # IR growth should track the source size, and every pair retains its check.
    sizes = []
    for count in (100, 1600):
        directory = root / f'guards-{count}'
        directory.mkdir()
        (directory / 'main.dyn').write_text(
            'fn main() {\n values := [1, 2, 3]\n index: usize = 0\n' +
            ' _ = index + 1\n _ = values[index]\n' * count + '}\n')
        output = directory / 'guards'
        build(directory, output, '--emit-ir', '--no-link')
        ir = output.with_suffix('.ll').read_text()
        assert ir.count('icmp ult i64') >= count, (count, 'missing bounds checks')
        sizes.append(len(ir))
    assert sizes[1] < sizes[0] * 20, sizes

print('PASS backend ranges, compound targets, NaN, guard dominance, string bytes '
      '(debug/release), and bounded guard IR')
