#!/usr/bin/env python3
"""Backend safety checks, expression evaluation, strings, and guard scaling."""
import os
from pathlib import Path
import re
import subprocess
import shlex
import sys
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


CLOSED_SUM = """fn main() {
  values: [4]u8 = [1, 2, 3, 4]
  sum: u32 = 0
  i: usize = 0
  for i <= 3 {
    sum += #cast(u32, values[i])
    i += 1
  }
  if sum != 10 { #panic("CLOSED SUM") }
}
"""
CASES['closed_sum'] = (CLOSED_SUM, None)
CASES['closed_bounds'] = (CLOSED_SUM.replace('i <= 3', 'i <= 4'), 'index.ok')
CASES['closed_maximum'] = ("""fn main() {
  i: u8 = 254
  for i <= 255 { i += 1 }
  #panic("WRAPPED")
}
""", 'overflow.ok')
CASES['closed_accumulator'] = ("""fn main() {
  sum: u8 = 250
  i: usize = 0
  for i <= 3 { sum += 2
  i += 1 }
  #panic("WRAPPED")
}
""", 'overflow.ok')
# Preserve rejection of mutable bounds/steps and multiple loop-carried writes.
for original in ('range_mutated_bound', 'range_mutated_step', 'range_multiple_writes'):
    source, error = CASES[original]
    CASES['closed_' + original] = (source.replace('i < ', 'i <= '), error)
CASES['closed_multiple_increments'] = ("""fn main() {
  i: u8 = 254
  for i <= 254 { i += 1
  i += 1 }
  #panic("WRAPPED")
}
""", 'overflow.ok')
# A runtime check inside a condition emits its failure path, which runs the
# pending defer and its comparison. That comparison must not decide the
# outer branch.
CASES['nested_condition'] = ("""struct State { flag: bool, operator: u32, count: u32 }
fn step(state: *State) bool {
  defer {
    if state.operator == 0 { state.count = 0 }
  }
  if state.flag { return true }
  return false
}
fn main() {
  state := State{flag: true, operator: 0, count: 3}
  if !step(&state) { #panic("NESTED CONDITION") }
  state.flag = false
  if step(&state) { #panic("NESTED CONDITION FALSE") }
}
""", None)
CASES['closed_call'] = ("""fn change(p: *u8) { p.* = 255 }
fn main() {
  i: u8 = 0
  for i <= 3 { change(&i)
  i += 1 }
  #panic("WRAPPED")
}
""", 'overflow.ok')


# A terminating cleanup replaces each exit and prevents older cleanups from
# being emitted after its LLVM terminator.
for name, body in {
    'panic': 'defer { #panic("older") }\ndefer { #panic("cleanup") }\n#panic("original")',
    'return': 'defer { #panic("older") }\ndefer { #panic("cleanup") }\nreturn 0',
    'fallthrough': 'if true { defer { #panic("older") }\ndefer { #panic("cleanup") } }\nreturn 0',
    'guard': 'defer { #panic("older") }\ndefer { #panic("cleanup") }\nreturn 1/a',
    'break': 'for i in 0..1 { defer { #panic("older") }\ndefer { #panic("cleanup") }\nbreak }\nreturn 0',
    'continue': 'for i in 0..1 { defer { #panic("older") }\ndefer { #panic("cleanup") }\ncontinue }\nreturn 0',
}.items():
    CASES['cleanup_' + name] = (
        'fn fail(a:u64) u64 {' + body + '}\nfn main() { _=fail(0) }\n', 'cleanup')


CASES['array_rvalue_index'] = ("""order:u64=0
struct Record { values:[2]u64 }
fn index() usize { order=order*10+1
return 1 }
fn values() [2]u64 { order=order*10+2
return [11,22] }
fn nested() [2][2]u64 { return [[1,2],[3,4]] }
fn record() Record { return Record{values:[5,6]} }
fn main() {
  if values()[index()]!=22 || order!=12 { #panic("EVALUATION ORDER") }
  f:=values
  if f()[0]!=11 || order!=122 { #panic("INDIRECT ARRAY") }
  if nested()[1][0]!=3 || record().values[1]!=6 || ([7,8])[0]!=7 { #panic("ARRAY VALUE") }
}
""", None)
CASES['array_rvalue_bounds'] = ("""fn values() [2]u64 { return [11,22] }
fn main() { i:usize=2
_=values()[i]
#panic("BOUNDS SKIPPED") }
""", 'index.ok')


def build(directory, output, *options):
    result = subprocess.run(
        [DYN, 'build', str(directory), '--no-cache', '--jobs', '1',
         '--output', str(output), *options],
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, (directory.name, options, result.stderr)


with tempfile.TemporaryDirectory(prefix='dyn-backend-regressions-') as temporary:
    root = Path(temporary)
    if sys.platform == 'linux':
        directory = root / 'foreign-global-alias'
        directory.mkdir()
        (directory / 'main.dyn').write_text('''extern value "backend_foreign_value": u64
extern plain: u64
fn initial() u64 { return value + plain }
ordinary: u64 = initial()
pub fn check() u64 {
  if ordinary != 24 || value != 11 || plain != 13 { return 1 }
  value += 2
  plain += 3
  return 0
}
''')
        host = root / 'foreign-host.c'
        host.write_text('''#include <dlfcn.h>
#include <stdint.h>
#include <string.h>
struct guarded { uint64_t value, canary; };
struct guarded backend_foreign_value = {11, UINT64_C(0xabcdef0123456789)};
struct guarded plain = {13, UINT64_C(0xfedcba9876543210)};
int main(int argc, char **argv) {
  if (argc != 2) return 2;
  void *library = dlopen(argv[1], RTLD_NOW);
  if (!library) return 3;
  if (backend_foreign_value.value != 11 || plain.value != 13 ||
      backend_foreign_value.canary != UINT64_C(0xabcdef0123456789) ||
      plain.canary != UINT64_C(0xfedcba9876543210)) return 4;
  void *symbol = dlsym(library, "check");
  uint64_t (*check)(void); memcpy(&check, &symbol, sizeof(check));
  if (!check || check() || backend_foreign_value.value != 13 || plain.value != 16 ||
      backend_foreign_value.canary != UINT64_C(0xabcdef0123456789) ||
      plain.canary != UINT64_C(0xfedcba9876543210)) return 5;
  return dlclose(library) != 0;
}
''')
        executable = root / 'foreign-host'
        subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), str(host),
                        '-Wl,--export-dynamic', '-ldl', '-o', str(executable)], check=True)
        for release in (False, True):
            output = directory / ('release.so' if release else 'debug.so')
            build(directory, output, '--shared', *(['--release'] if release else ['--debug']))
            result = subprocess.run([str(executable), str(output)], capture_output=True,
                                    text=True, timeout=10)
            assert result.returncode == 0, ('foreign-global-alias', release, result.returncode, result.stderr)
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
            if name.startswith('cleanup_'):
                assert result.returncode == 101, (name, release, diagnostic)
                assert result.stderr.splitlines()[0] == 'cleanup', (name, release, diagnostic)
                assert 'older' not in diagnostic and 'original' not in diagnostic, (name, diagnostic)
                if not release:
                    assert 'fail' in result.stderr and 'stack trace:' in result.stderr, (name, diagnostic)

    directory = root / 'closed-usize-wasm32'
    directory.mkdir()
    (directory / 'main.dyn').write_text("""fn main() {
  i: usize = 4294967294
  for i <= 4294967295 { i += 1 }
}
""")
    output = directory / 'wasm32'
    build(directory, output, '--target', 'wasm32-wasi', '--emit-asm', '--no-link')
    assembly = output.with_suffix('.s').read_text()
    assert re.search(r'i64\.add\s+(?:\S+\s+){0,4}i64\.const 4294967295\s+i64\.le_u', assembly), assembly

    # usize must use the target width rather than the host's 64-bit width.
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
    build(directory, output, '--target', 'wasm32-wasi', '--emit-asm', '--no-link')
    assembly = output.with_suffix('.s').read_text()
    assert re.search(r'i64\.add\s+(?:\S+\s+){0,4}i64\.const 4294967295\s+i64\.le_u', assembly), assembly

    # Exercise thousands of guard pairs without comparing wall-clock timings.
    # Code growth should track the source size, and every pair retains its check.
    sizes = []
    for count in (100, 1600):
        directory = root / f'guards-{count}'
        directory.mkdir()
        (directory / 'main.dyn').write_text(
            'fn main() {\n values := [1, 2, 3]\n index: usize = 0\n' +
            ' _ = index + 1\n _ = values[index]\n' * count + '}\n')
        output = directory / 'guards'
        build(directory, output, '--emit-asm', '--no-link')
        assembly = output.with_suffix('.s').read_text()
        assert assembly.count('cmp ') >= count, (count, 'missing bounds checks')
        sizes.append(len(assembly))
    assert sizes[1] < sizes[0] * 20, sizes

    # Iterating a large array by value copies it with a loop, not one load and
    # store per word.
    directory = root / 'large-copy'
    directory.mkdir()
    (directory / 'main.dyn').write_text('''values: [65536]u64
fn main() {
  values[3] = 7
  total: u64 = 0
  for value in values { total += value }
  if total != 7 { #panic("WRONG TOTAL") }
}
''')
    output = directory / 'large-copy'
    build(directory, output, '--release')
    assert subprocess.run([str(output)], timeout=10).returncode == 0
    assert output.stat().st_size < 200_000, output.stat().st_size

print('PASS backend ranges, compound targets, NaN, guard dominance, string bytes '
      '(debug/release), and bounded guard code')
