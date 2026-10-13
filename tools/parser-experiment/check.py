#!/usr/bin/env python3
"""Differential scalar-expression experiment; never changes the compiler parser."""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import random
import shlex
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--samples', type=int, default=500)
parser.add_argument('--benchmark', action='store_true')
parser.add_argument('--sanitize', action='store_true')
args = parser.parse_args()
if args.samples < 1:
    parser.error('--samples must be positive')
grammar = Path(os.environ.get('TS_DIR', ROOT / 'build/deps/tree-sitter-dyn')).resolve()
build = Path(os.environ.get('BUILD', ROOT / 'build')).resolve() / 'parser-experiment-work'
build.mkdir(parents=True, exist_ok=True)
cc = shlex.split(os.environ.get('CC', 'cc'))
flags = ['-std=c11', '-Wall', '-Wextra', '-Wpedantic', '-Werror', '-g', '-O2']
if args.sanitize:
    flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
exe = build / 'parse'
subprocess.run([*cc, *flags, str(HERE/'parser.c'), str(HERE/'driver.c'),
                str(grammar/'src/parser.c'), str(grammar/'src/scanner.c'),
                '-I', str(grammar/'src'), '-ltree-sitter', '-o', str(exe)], check=True)
unit = build / 'unit'
subprocess.run([*cc, *flags, str(HERE/'unit.c'), '-o', str(unit)], check=True)
subprocess.run([str(unit)], check=True)

def run(mode, expression, repeats=None):
    data = expression.encode() if isinstance(expression, str) else expression
    command = [str(exe), mode]
    if repeats is not None:
        command.append(str(repeats))
    result = subprocess.run(command, input=data, capture_output=True, timeout=20)
    if result.returncode not in (0, 1):
        raise AssertionError((mode, data, result.returncode, result.stderr.decode(errors='replace')))
    if result.returncode:
        assert result.stderr.startswith(b'invalid expression'), (mode, data, result.stderr)
        assert b'ERROR:' not in result.stderr and b'runtime error:' not in result.stderr, result.stderr
    else:
        assert not result.stderr, (mode, data, result.stderr)
    return None if result.returncode else json.loads(result.stdout)

checked = 0

def compare(expression, valid=None):
    global checked
    fast, tree = run('fast', expression), run('tree', expression)
    assert fast == tree, (expression, fast, tree)
    if valid is not None:
        assert (fast is not None) == valid, (expression, valid, fast)
    checked += 1

operators = ['||', '&&', '==', '!=', '<', '>', '<=', '>=', '|', '^', '&', '<<', '>>', '+', '-', '*', '/', '%']
for first in operators:
    for second in operators:
        compare(f'a {first} b {second} c', True)
for expression in [
    'a', 'a.true', 'a.fn', '_', 'true', 'false', 'nil', '0x_FF', '0b_10', '0o_7', '1_000',
    '1.', '.2e-3', '3.25E+7', '1e3', '"hello"', r'"a\n\x41\u{1f600}"',
    "'é'", "'😀'", r"'\u{1f600}'", r"'\''", '""',
    '-a.*', '~!a', 'a.*.b(x, y,)[0].*', 'f()', 'f(a,)', '#wrap(a+b)', '#len(a)',
    '(a+b)(c)', '(1).x', '(-a)[b]', '(1).*',
    'a[..]', 'a[x..]', 'a[..y]', 'a[x..y]', 'a[/*lo*/ .. /*hi*/]',
    'a./* comment */b', 'a/*x*/+/*y*/b', 'a//line\n+b',
    '"/*not comment*/"', 'a[.5]', 'a[1..2]', 'a[1...2]',
]:
    compare(expression, True)
for expression in [
    '', ' ', 'a +', '(a', 'a)', 'a b', 'a[]', 'a[..=b]', 'f(,a)',
    'f(a,,b)', '1(a)', 'true.x', '#wrap()', '#len(a,b)', 'a.', 
    '"unterminated', "''", "'ab'", "'a", '"a\nb"', r'"\q"', r'"\x0"',
    r'"\u{}"', '/* unterminated', '0x', '0b2', '1e', '1.e2', 'a += b', '1.*',
]:
    compare(expression, False)

rng = random.Random(20261013)
atoms = ['a', 'value', 'p', 'x', '42', '.25', '2.5e-2', '0xFF', 'true', 'nil', '"text"', "'é'"]
def expression(depth):
    if not depth or rng.randrange(5) == 0:
        return rng.choice(atoms)
    shape = rng.randrange(8)
    if shape == 0:
        return rng.choice(['-', '~', '!', '&']) + '(' + expression(depth-1) + ')'
    if shape == 1:
        return '(' + expression(depth-1) + ')'
    if shape == 2:
        return 'call(' + ', '.join(expression(depth-1) for _ in range(rng.randrange(4))) + ')'
    if shape == 3:
        return 'obj.' + rng.choice(['field', 'value', 'next'])
    if shape == 4:
        return 'items[' + expression(depth-1) + ']'
    if shape == 5:
        return rng.choice(['#wrap(', '#len(']) + expression(depth-1) + ')'
    if shape == 6:
        return '(' + expression(depth-1) + ').*'
    return expression(depth-1) + ' ' + rng.choice(operators) + ' ' + expression(depth-1)
for _ in range(args.samples):
    source = expression(4)
    compare(source, True)
    # Mutations test rejection and any alternative valid interpretation equally.
    at = rng.randrange(len(source))
    compare(source[:at] + source[at+1:])
    compare(source + rng.choice([')', ']', '+', ',']))
# Explicit experiment limits and unsupported syntax must fail, not partially parse.
for source in ['('*300 + 'a' + ')'*300, '[1,2]', 'Point{x:1}', '#cast(i32)x', 'f($T)']:
    assert run('fast', source) is None
print(f'PASS {checked} differential expressions: shape, byte spans, operators and rejection')
if args.benchmark:
    source = ' + '.join(f'call(value{i}, items[{i}]) * (x - {i})' for i in range(100))
    compare(source, True)
    values = {'fast': [], 'tree': []}
    for sample in range(5):
        for mode in (['fast', 'tree'] if sample % 2 == 0 else ['tree', 'fast']):
            result = run(mode, source, 1000)
            values[mode].append(result['seconds'])
    report = {'bytes': len(source.encode()), 'iterations': 1000,
              'host': platform.platform(),
              'compiler': subprocess.check_output([*cc, '--version'], text=True).splitlines()[0],
              'flags': flags,
              'sha256': {str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p):
                         hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in [HERE/'parser.c', HERE/'parser.h', HERE/'driver.c',
                                   grammar/'src/parser.c', grammar/'src/scanner.c']},
              'samples_cpu_seconds': values,
              'median_cpu_seconds': {k: statistics.median(v) for k, v in values.items()},
              'fast_tree': run('fast', source, 2),
              'scope': 'Scalar expression only; excludes module loading, AST lowering, semantics and machine code. Reuses parser/storage in both modes.'}
    (build/'benchmark.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
