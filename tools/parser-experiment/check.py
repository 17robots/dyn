#!/usr/bin/env python3
"""Differential expression/source experiment; never changes the compiler parser."""
import argparse
import hashlib
import importlib.util
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
parser.add_argument('--sources', action='store_true', help='Also compare complete source trees for each corpus file')
parser.add_argument('--corpus', type=Path, action='append', default=[], help='Extract expressions from all .dyn files under this path; repeatable')
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
snapshot_unit = build / 'snapshot-unit'
subprocess.run([*cc, *flags, str(HERE/'snapshot-unit.c'), '-pthread', '-o', str(snapshot_unit)], check=True)
subprocess.run([str(snapshot_unit)], check=True)

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
source_checked = 0

def compare(expression, valid=None):
    global checked
    fast, tree = run('fast', expression), run('tree', expression)
    assert fast == tree, (expression, fast, tree)
    if valid is not None:
        assert (fast is not None) == valid, (expression, valid, fast)
    checked += 1

def compare_source(source, valid=None, location=None):
    global source_checked
    fast, tree = run('source-fast', source), run('source-tree', source)
    assert fast == tree, (location, source, fast, tree)
    if valid is not None:
        assert (fast is not None) == valid, (location, source, valid, fast)
    source_checked += 1

source_cases = json.loads((HERE/'source-cases.json').read_text())
for case in source_cases:
    compare_source(case['source'], case.get('valid'))
extract_spec = importlib.util.spec_from_file_location('extract_tests', HERE/'extract-tests.py')
extract_tests = importlib.util.module_from_spec(extract_spec)
extract_spec.loader.exec_module(extract_tests)
for case in extract_tests.extract_test_sources(ROOT):
    compare_source(case['source'], location=f"{case['path']}:{case['line']}")
source_rng = random.Random(20261014)
for _ in range(args.samples):
    source = source_rng.choice(source_cases)['source']
    if source:
        at = source_rng.randrange(len(source))
        compare_source(source[:at] + source[at+1:])
    compare_source(source + source_rng.choice(['}', ')', ' fn', ' #target()', ' /*']))

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
    '', ' ', 'a\nconst other := b', 'a\n#link("c")', 'a +', '(a', 'a)', 'a b', 'a[]', 'a[..=b]', 'f(,a)',
    'f(a,,b)', '1(a)', 'true.x', '#wrap()', '#len(a,b)', 'a.', 
    '"unterminated', "''", "'ab'", "'a", '"a\nb"', r'"\q"', r'"\x0"',
    r'"\u{}"', '/* unterminated', '0x', '0b2', '1e', '1.e2', 'a += b', '1.*',
]:
    compare(expression, False)

# Keywords remain identifiers when the grammar has no competing keyword rule.
for word in 'fn pub use const type distinct packed struct enum extern return continue break if else case is for in defer i8 i16 i32 i64 u8 u16 u32 u64 f32 f64 isize usize bool rawptr any'.split():
    compare(word, True)
    compare('a.' + word, True)
    compare('(' + word + ') + x', True)
for source in ['/* before */ a /* after */', 'a // after', 'a\\n/* after */']:
    compare(source.replace('\\n', '\n'), True)

for source in ['f(i32)', 'f(*i32)', 'f([]const u8)', 'f($T)',
               '#cast(i32)x + y', '#bitcast(*fn(i32)u8)p',
               '#sizeof(true)', '#sizeof(false)', '#sizeof(nil)', '#sizeof(i32)', '#sizeof(T)', '#sizeof(a.b)', '#sizeof(a+b)',
               '#typeof([]u8)', '#offsetof(T,x)', '#load("x")', '#syscall(1,a)',
               'Point{x:1,y:2}', 'm.Point{}', '.{}', '[1,2]',
               'f([2+3]i32)', 'f(fn)', 'f(true)', '#cast(*const T)p',
               '#alignof([4]*const m.T)',
               'f([1,2])', '#sizeof([1,2])', '#syscall()',
               'Point{x:[1,2],y:.{a:#cast(i32)x}}']:
    compare(source, True)

for source in ['true{}', 'false{}', 'nil{}', 'true.T{}', '#len(&(#alignof#typeof(nil))))', 'f(i32+x)', 'f(i32())', '#sizeof(i32+x)', '\v1.', 'a\u0085+b', 'a\u00a0+b', 'a\u2003+b', 'a\u2028+b']:
    compare(source, False)

for word in 'fn pub use const type distinct packed struct enum extern'.split():
    compare('#cast(*fn()' + word + ')x', False)
for source in ['#sizeof([1]*u8)', '#alignof([]*u8)', '#typeof([1]*fn())', 'f([1]*u8)', 'f([1]*x+y)', 'f([1]*const T)',
               'f([1,]*u8)', 'f([1,2]*u8)', '#sizeof([1]*x+y)',
               'f([' * 22 + '1' + '])' * 22]:
    compare(source, True)

rng = random.Random(20261013)
atoms = ['a', 'value', 'p', 'x', '42', '.25', '2.5e-2', '0xFF', 'true', 'nil', '"text"', "'é'"]
def expression(depth):
    if not depth or rng.randrange(5) == 0:
        return rng.choice(atoms)
    shape = rng.randrange(15)
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
    if shape == 7:
        return '#cast(' + rng.choice(['i32', '*const u8', '[]u8', '[4]i32', '*fn(i32)u8', '$T', 'm.T']) + ')' + '(' + expression(depth-1) + ')'
    if shape == 8:
        return '[' + ','.join(expression(depth-1) for _ in range(rng.randrange(4))) + ']'
    if shape == 9:
        return rng.choice(['Point', 'm.Point', '.']) + '{x:' + expression(depth-1) + ',y:' + expression(depth-1) + '}'
    if shape == 10:
        return rng.choice(['#sizeof(', '#alignof(', '#typeof(']) + expression(depth-1) + ')'
    if shape == 11:
        return 'call(' + rng.choice(['i32', '*u8', '[]const u8', '$T', '[2+3]m.T', '*fn(i32)u8']) + ',' + expression(depth-1) + ')'
    if shape == 12:
        return '#offsetof(m.Point,x)'
    if shape == 13:
        return '#syscall(' + expression(depth-1) + ')'
    return expression(depth-1) + ' ' + rng.choice(operators) + ' ' + expression(depth-1)
for _ in range(args.samples):
    source = expression(4)
    compare(source, True)
    # Mutations test rejection and any alternative valid interpretation equally.
    at = rng.randrange(len(source))
    compare(source[:at] + source[at+1:])
    compare(source + rng.choice([')', ']', '+', ',']))
# Explicit experiment limits and unsupported syntax must fail, not partially parse.
for source in ['('*300 + 'a' + ')'*300, '#panic(x)', '#reverse(x)', 'fn main() {}']:
    assert run('fast', source) is None
if args.corpus:
    corpus_report = {'files': [], 'expressions': 0, 'mismatches': [], 'invalid_sources': [], 'source_mismatches': []}
    for directory in args.corpus:
        if not directory.exists():
            raise SystemExit(f'missing corpus: {directory}')
        paths = sorted(path for path in directory.rglob('*.dyn')
                       if not {'.jj', '.git', 'build', '.cache'}.intersection(path.relative_to(directory).parts)) if directory.is_dir() else [directory]
        for path in paths:
            data = path.read_bytes()
            corpus_report['files'].append({'path': str(path), 'sha256': hashlib.sha256(data).hexdigest()})
            if args.sources:
                actual, expected = run('source-fast', data), run('source-tree', data)
                if actual != expected:
                    corpus_report['source_mismatches'].append({'path': str(path), 'actual': actual, 'expected': expected})
            extracted = run('corpus', data)
            if extracted is None:
                corpus_report['invalid_sources'].append(str(path))
                continue
            for entry in extracted:
                source = data[entry['start']:entry['end']]
                actual = run('fast', source)
                corpus_report['expressions'] += 1
                if actual != entry['tree']:
                    corpus_report['mismatches'].append({'path': str(path), 'start': entry['start'],
                        'end': entry['end'], 'source': source.decode(errors='replace'),
                        'actual': actual, 'expected': entry['tree']})
    (build/'corpus.json').write_text(json.dumps(corpus_report, indent=2)+'\n')
    print(f"Corpus: {len(corpus_report['files'])} files, {corpus_report['expressions']} expressions, "
          f"{len(corpus_report['invalid_sources'])} invalid sources, {len(corpus_report['mismatches'])} expression mismatches, {len(corpus_report['source_mismatches'])} source mismatches")
    assert not corpus_report['mismatches'] and not corpus_report['source_mismatches'], f"see {build/'corpus.json'}"
print(f'PASS {checked} differential expressions and {source_checked} source cases: shape, byte spans, operators, modifiers, field roles and rejection')
if args.benchmark:
    source = ' + '.join(f'call(value{i}, items[{i}]) * (x - {i})' for i in range(100))
    compare(source, True)
    values = {'fast': [], 'tree': []}
    for sample in range(5):
        for mode in (['fast', 'tree'] if sample % 2 == 0 else ['tree', 'fast']):
            result = run(mode, source, 1000)
            values[mode].append(result['seconds'])
    report = {'bytes': len(source.encode()), 'iterations': 1000,
              'workload_sha256': hashlib.sha256(source.encode()).hexdigest(),
              'host': platform.platform(),
              'compiler': subprocess.check_output([*cc, '--version'], text=True).splitlines()[0],
              'flags': flags,
              'sha256': {str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p):
                         hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in [HERE/'parser.c', HERE/'parser.h', HERE/'source.inc', HERE/'driver.c', HERE/'check.py',
                                   grammar/'src/parser.c', grammar/'src/scanner.c']},
              'samples_cpu_seconds': values,
              'median_cpu_seconds': {k: statistics.median(v) for k, v in values.items()},
              'fast_tree': run('fast', source, 2),
              'scope': 'Scalar expression only; excludes module loading, AST lowering, semantics and machine code. Reuses parser/storage in both modes.'}
    module_path = ROOT/'std/encoding/json/json.dyn'
    module = module_path.read_bytes()
    compare_source(module)
    module_values = {'source-fast': [], 'source-tree': []}
    for sample in range(5):
        order = ['source-fast', 'source-tree'] if sample % 2 == 0 else ['source-tree', 'source-fast']
        for mode in order:
            module_values[mode].append(run(mode, module, 100)['seconds'])
    report['source_workload'] = {'path': str(module_path.relative_to(ROOT)),
        'bytes': len(module), 'sha256': hashlib.sha256(module).hexdigest(), 'iterations': 100,
        'samples_cpu_seconds': module_values,
        'median_cpu_seconds': {k: statistics.median(v) for k, v in module_values.items()},
        'fast_tree': run('source-fast', module, 2),
        'scope': 'Single complete std source file; parsing only, no imports, semantic analysis, lowering, or codegen.'}
    (build/'benchmark.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
