#!/usr/bin/env python3
"""Qualify the opt-in compact declaration consumer against existing diagnostics."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

import syntax_messages

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--sanitize', action='store_true')
parser.add_argument('--compiler', type=Path, help='Opt-in dyn-compact-declarations binary')
parser.add_argument('--reference', type=Path, default=ROOT/'build/dyn-legacy')
args = parser.parse_args()
build = Path(os.environ.get('BUILD', ROOT/'build')).resolve()/'parser-experiment-work'
build.mkdir(parents=True, exist_ok=True)
grammar = Path(os.environ.get('TS_DIR', ROOT/'build/deps/tree-sitter-dyn')).resolve()
flags = ['-std=c11', '-D_POSIX_C_SOURCE=200809L', '-Wall', '-Wextra', '-Wpedantic', '-Werror', '-g', '-O2',
         '-ffunction-sections', '-fdata-sections']
if args.sanitize:
    flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
exe = build/'declarations-unit'
subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), *flags,
    '-I', str(ROOT/'src'), '-I', str(grammar/'src'), str(HERE/'declarations-unit.c'), str(HERE/'parser.c'),
    *[str(ROOT/'src'/name) for name in ('ast.c', 'sema.c', 'sema_globals.c', 'source.c', 'source_tree.c', 'diagnostic.c', 'target.c')],
    str(grammar/'src/parser.c'), str(grammar/'src/scanner.c'), '-ltree-sitter',
    '-Wl,--gc-sections,--wrap=realloc', '-o', str(exe)], check=True)
subprocess.run([exe], check=True, timeout=60)
if args.compiler:
    cases = [case['source'] for case in json.loads((HERE/'source-cases.json').read_text())]
    cases += ['fn main() {}', 'pub fn main(){}', 'fn main(){} fn main(){}',
              'fn main(x:i64) i64 {return x}', 'fn main(){if {return}}',
              'fn main(){'+('x:=\n'*30)+'}',
              'fn main(){_='+('('*300)+'1'+(')'*300)+'}',
              'fn main(){_='+('+'.join(['1']*1100))+'}',
              'fn main(){x:'+('*'*300)+'u8}',
              'fn main(){'+('if true{'*300)+('}'*300)+'}']
    # Both sides of the raw 1024-level guard, with primary/prefix/token depth.
    cases += ['fn main(){_='+('(' * n)+'1'+(')' * n)+'}' for n in (508, 509, 510, 511)]
    cases += ['fn main(){_='+('+'.join(['1'] * n))+'}' for n in (1019, 1020, 1021, 1022, 1023)]
    with tempfile.TemporaryDirectory(prefix='dyn-compact-declarations-') as directory:
        root = Path(directory)
        for index, source in enumerate(cases):
            (root/'main.dyn').write_text(source)
            for diagnostic_flags in ([], ['--diagnostics', 'json']):
                results = []
                for binary in (args.reference, args.compiler):
                    result = subprocess.run([str(binary.resolve()), 'check', root, '--quiet', *diagnostic_flags],
                                            capture_output=True, timeout=30)
                    assert result.returncode in (0, 1, 2), (index, result)
                    assert not any(x in result.stderr for x in (b'AddressSanitizer', b'runtime error:', b'LeakSanitizer'))
                    results.append((result.returncode, result.stdout, result.stderr))
                assert syntax_messages.equivalent(results[0], results[1]), (index, source, diagnostic_flags, results)
    print(f'PASS {len(cases)} compiler diagnostic/depth cases in text and JSON modes')
