#!/usr/bin/env python3
"""Compare direct compact AST lowering with production Tree-sitter."""
import argparse
import os
import json
import re
import tempfile
from pathlib import Path
import shlex
import subprocess
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--sanitize', action='store_true')
p.add_argument('--corpus', action='append', type=Path, default=[])
a = p.parse_args()
grammar = Path(os.environ.get('TS_DIR', ROOT/'build/deps/tree-sitter-dyn')).resolve()
build = Path(os.environ.get('BUILD', ROOT/'build')).resolve()/'parser-experiment-work'
build.mkdir(parents=True, exist_ok=True)
flags = ['-std=c11','-DDYN_EXPERIMENT_COMPACT_SOURCES','-DDYN_EXPERIMENT_COMPACT_AST','-D_POSIX_C_SOURCE=200809L',
         '-Wall','-Wextra','-Wpedantic','-Werror','-O2','-g']
if a.sanitize: flags += ['-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-omit-frame-pointer']
exe = build/'ast-unit'
subprocess.run([*shlex.split(os.environ.get('CC','cc')),*flags,'-I',str(ROOT/'src'),'-I',str(grammar/'src'),
    str(HERE/'ast-unit.c'),str(HERE/'parser.c'),str(HERE/'snapshot.c'),
    *[str(ROOT/'src'/name) for name in ('source.c','source_tree.c','diagnostic.c','target.c')],
    str(grammar/'src/parser.c'),str(grammar/'src/scanner.c'),'-ltree-sitter','-o',str(exe)],check=True)
corpus = sorted({p.resolve() for folder in a.corpus for p in folder.rglob('*.dyn')})
# Trivia can expose raw-child assumptions in the retained reference lowerer.
# Keep those diagnostics exact through explicit compatibility fallbacks.
examples = [
    'struct S {x:i64=1} type A=S const N:i64=3 fn f(a,b:i64) i64 {s:=S{x:a} _=s.x _=a+b return a}',
    'enum(u8) E {A=1,B:i64} fn f(){_=a.b{x:1} _=a.b(1) _=#sizeof(a.b) _=#cast(*const u8)1}',
    'fn f(a:i64){if a>0 {a=2} else {a=1} for i in 0..=3 {_=i} case a {1,2=>{}, _=>{}}}',
    'fn f(a:$T) T {return a} fn g($T:type,x:T) T {return x} fn main(){_=f(i32,1)}',
]
with tempfile.TemporaryDirectory(prefix='dyn-compact-ast-') as temporary:
    folder = Path(temporary)
    cases = [case['source'] for case in json.loads((HERE/'source-cases.json').read_text())]
    for source in examples:
        for match in re.finditer(r'\s+|(?<=[\w])(?=[{}\[\]().,:=+*])|(?<=[{}\[\]().,:=+*])(?=[\w])', source):
            cases.append(source[:match.start()] + ' /*trivia*/ ' + source[match.end():])
    fixtures = []
    for i, source in enumerate(cases):
        file = folder/f'{i:04}.dyn'
        file.write_text(source)
        fixtures.append(file)
    subprocess.run([str(exe), *map(str, fixtures), *map(str, corpus)], check=True, timeout=120)
