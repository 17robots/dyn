#!/usr/bin/env python3
"""Compare compact serialized module interfaces with the production reader."""
import argparse
import os
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
flags = ['-std=c11','-DDYN_EXPERIMENT_COMPACT_SOURCES','-D_POSIX_C_SOURCE=200809L',
         '-Wall','-Wextra','-Wpedantic','-Werror','-O2','-g','-ffunction-sections','-fdata-sections']
if a.sanitize: flags += ['-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-omit-frame-pointer']
exe = build/'interface-unit'
subprocess.run([*shlex.split(os.environ.get('CC','cc')),*flags,'-I',str(ROOT/'src'),'-I',str(grammar/'src'),
    str(HERE/'interface-unit.c'),str(HERE/'parser.c'),str(HERE/'snapshot.c'),
    *[str(ROOT/'src'/name) for name in ('source.c','source_tree.c','diagnostic.c','target.c')],
    str(grammar/'src/parser.c'),str(grammar/'src/scanner.c'),'-ltree-sitter','-pthread',
    '-Wl,--gc-sections','-o',str(exe)],check=True)
corpus=sorted({p.resolve() for folder in [ROOT/'std', ROOT/'tests', *a.corpus] for p in folder.rglob('*.dyn')})
subprocess.run([str(exe),*map(str,corpus)],check=True,timeout=120)
