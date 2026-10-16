#!/usr/bin/env python3
"""Independent optimization must change code while preserving observable behavior."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn')).resolve())
SOURCE = '''
state: i64 = 0
fn effect() bool { state += 1 return true }
fn branches() i64 { if true { return 7 } else { return 9 } }
fn polynomial(x: i64) i64 { return (x * 3 + 7) * 5 }
fn main() {
  if branches() != 7 { #panic("branch returns") }
  immutable: i64 = 19
  if immutable != 19 { #panic("immutable") }
  mutable: i64 = 3
  pointer := &mutable
  pointer.* = 9
  if mutable != 9 { #panic("alias") }
  if false && effect() { #panic("short circuit") }
  if true || effect() { state += 4 }
  if state != 4 { #panic("effects") }
  if true { defer { state += 8 } state += 2 } else { #panic("dead") }
  if state != 14 { #panic("defer") }
  if polynomial(19) != 320 { #panic("constant call") }
  a: i8 = -128
  b: u64 = 18446744073709551615
  if a >= 0 || b < 18446744073709551614 { #panic("signedness") }
}
'''

def run(*args, success=True):
    p = subprocess.run([str(x) for x in args], cwd=ROOT, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert (p.returncode == 0) == success, (args, p.returncode, p.stdout, p.stderr)
    return p

with tempfile.TemporaryDirectory(prefix='dyn-native-opt-') as directory:
    work = Path(directory)
    module = work/'module'
    module.mkdir()
    (module/'main.dyn').write_text(SOURCE)
    sizes = []
    for level in (1, 2, 3):
        output = work/f'o{level}'
        result = run(DYN, 'build', module, '--backend', 'native', '--release',
                     '--opt-level', level, '--opt-remarks', '--emit-object', '--output', output)
        run(output)
        sizes.append(output.with_suffix('.o').stat().st_size)
        counts = re.findall(r'(\d+) scalar folds, (\d+) immutable loads, (\d+) constant branches, (\d+) constant calls', result.stderr)
        assert counts, result.stderr
        totals = [sum(int(row[i]) for row in counts) for i in range(4)]
        if level == 1:
            assert totals[1:] == [0, 0, 0], totals
        if level >= 2:
            assert totals[1] and totals[2], totals
        if level == 3:
            assert totals[3], totals
    assert sizes[0] > sizes[1] > sizes[2], ('expected real object reduction', sizes)
    # Hotness changes the actual specialization budget, not only cache keys.
    expression = ' + '.join(['x'] * 20)
    (module/'main.dyn').write_text(f'fn hot(x: i64) i64 {{ return {expression} }}\nfn main() {{ if hot(1) != 20 {{ #panic("profile") }} }}\n')
    profile = work/'samples.prof'
    observed = []
    for count in (1, 1000):
        profile.write_text(f'hot:{count}:1\n 1: {count}\n')
        output = work/f'profile{count}'
        result = run(DYN, 'build', module, '--backend', 'native', '--release',
                     '--sample-profile', profile, '--opt-remarks', '--output', output)
        run(output)
        observed.append(sum(map(int, re.findall(r'(\d+) constant calls', result.stderr))))
    assert observed[0] == 0 and observed[1] > 0, observed
    for contents in ('', 'invalid\n', 'hot:1:1\n 1: broken\n', 'hot:18446744073709551616:1\n'):
        profile.write_text(contents)
        run(DYN, 'build', module, '--backend', 'native', '--release',
            '--sample-profile', profile, '--output', work/'invalid', success=False)
    (module/'main.dyn').write_text('''
fn left(a: u64, b: u64) u64 { return a << b }
fn right(a: u64, b: u64) u64 { return a >> b }
fn signed_right(a: i64, b: u64) i64 { return a >> b }
fn main() {
  if left(3, 4) != 48 || right(0x8000000000000000, 63) != 1 || signed_right(-8, 2) != -2 {
    #panic("CPU shifts")
  }
}
''')
    for cpu in ('generic', 'native'):
        output = work/f'cpu-{cpu}'
        result = run(DYN, 'build', module, '--backend', 'native', '--release', '--cpu', cpu,
                     '--opt-remarks', '--output', output)
        run(output)
        run(DYN, 'build', module, '--backend', 'native', '--release', '--cpu', cpu,
            '--emit-object', '--no-link', '--output', output)
        data = output.with_suffix('.o').read_bytes()
        if cpu == 'native' and '+bmi2 variable shifts' in result.stderr:
            assert bytes.fromhex('c4e2f1f7c0') in data, 'missing selected shlx'
            assert bytes.fromhex('c4e2f3f7c0') in data, 'missing selected shrx'
            assert bytes.fromhex('c4e2f2f7c0') in data, 'missing selected sarx'
    # Dynamic calls must preserve argument snapshots, local identities, lexical
    # cleanup and all return paths. These cannot use constant-call evaluation.
    (module/'main.dyn').write_text('''
state: i64 = 0
fn next() i64 { state += 1 return state }
fn choose(a: i64, b: i64) i64 {
  defer { state += 100 }
  if a > b { return a - b }
  for i in 0..b { if i == a { return a + b } }
  return b
}
fn recursive(n: i64) i64 { if n == 0 { return 7 } return recursive(n - 1) }
struct Pair { a: i64, b: i64 }
fn pair(x: i64) Pair { defer { state += 10 } return Pair{a: x, b: x + 2} }
fn mutate(p: *Pair) i64 { p.a = 999 return 0 }
fn take(p: Pair, ignored: i64) Pair { return p }
fn text(x: i64) []const u8 { if x > 0 { return "yes" } return "no" }
fn add(x: i64) { state += x }
fn captures() { defer add(next()) state += 10 }
pub fn exercise() {
  state = 0
  answer := choose(next(), next())
  if answer != 3 || state != 102 { #panic("argument/return/defer") }
  p := pair(next())
  if p.a != 103 || p.b != 105 || state != 113 { #panic("aggregate return") }
  snapshot := take(p, mutate(&p))
  if snapshot.a != 103 || p.a != 999 { #panic("argument snapshot") }
  r := recursive(4)
  if r != 7 { #panic("recursion") }
  s := text(next())
  if #len(s) != 3 { #panic("descriptor") }
  answer = choose(4, 2)
  if answer != 2 || state != 214 { #panic("second expansion") }
  captures()
  if state != 440 { #panic("deferred argument capture") }
}
fn main() { exercise() }
''')
    for level in (2, 3):
        output = work/f'inline-{level}'
        result = run(DYN, 'build', module, '--release', '--opt-level', level,
                     '--opt-remarks', '--emit-ir', '--output', output)
        run(output)
        if level == 3:
            count = sum(map(int, re.findall(r'(\d+) direct calls inlined', result.stderr)))
            assert count >= 5, result.stderr
            ir = output.with_suffix('.ll').read_text()
            exercise = re.search(r'define[^\n]*@exercise\([^\n]*\)\s*\{(.*?)\n\}', ir, re.S)
            assert exercise, ir
            assert not re.search(r'call[^\n]*@(choose|pair|take|text|captures)\(', exercise[1]), exercise[1]
            assert re.search(r'call[^\n]*@next\(', exercise[1]), 'argument effects must remain'
    # The same transformed IR feeds every target. Reassemble with an optional
    # oracle; execution on foreign hosts remains the corresponding CI job.
    for target in ('x86_64-linux', 'aarch64-linux', 'aarch64-macos', 'x86_64-macos', 'x86_64-windows', 'aarch64-windows',
                   'wasm32-browser', 'wasm32-wasi'):
        run(DYN, 'build', module, '--release', '--opt-level', 3, '--target', target,
            '--emit-object', '--emit-ir', '--no-link', '--output', work/target,
            *(['--shared'] if target == 'wasm32-browser' else []))
    if shutil.which('node'):
        wasm = work/'inline.wasm'
        run(DYN, 'build', module, '--release', '--opt-level', 3, '--target',
            'wasm32-browser', '--shared', '--output', wasm)
        run('node', '-e', '''const fs=require('fs');
WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{}).then(({instance})=>{
  instance.exports.dyn_initialize(); instance.exports.exercise();
}).catch(e=>{console.error(e);process.exit(1)});''', wasm)

    (module/'main.dyn').write_text('''use "std/io" io
fn fail() { defer { _ = io.println(io.stdout(), "inner") } #panic("inline panic") }
fn main() { defer { _ = io.println(io.stdout(), "outer") } fail() }
''')
    for level in (2, 3):
        output = work/f'inline-panic-{level}'
        run(DYN, 'build', module, '--release', '--opt-level', level, '--output', output)
        result = run(output, success=False)
        assert result.stdout.splitlines() == ['inner', 'outer'], result.stdout
        assert 'inline panic' in result.stderr, result.stderr

    # Checked failure must remain a runtime failure at every optimization level.
    (module/'main.dyn').write_text('fn main() { a: i8 = 127 b: i8 = 1 _ = a + b }\n')
    for level in (1, 2, 3):
        output = work/f'trap{level}'
        run(DYN, 'build', module, '--backend', 'native', '--release', '--opt-level', level,
            '--output', output)
        run(output, success=False)
print('PASS independent optimization levels, effect ordering, aliases, inlining, deferred cleanup and checked overflow')
