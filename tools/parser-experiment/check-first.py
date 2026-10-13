#!/usr/bin/env python3
"""Prove compact-first source certification, fallback and failure ownership."""
import argparse,json,os,runpy,shlex,subprocess,tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--sanitize',action='store_true');a=p.parse_args()
grammar=Path(os.environ.get('TS_DIR',ROOT/'build/deps/tree-sitter-dyn')).resolve()
runpy.run_path(str(HERE/'grammar-pin.py'))['verify'](grammar)
build=Path(os.environ.get('BUILD',ROOT/'build')).resolve()/'parser-experiment-work';build.mkdir(parents=True,exist_ok=True)
flags=['-std=c11','-D_POSIX_C_SOURCE=200809L','-O2','-g','-Wall','-Wextra','-Wpedantic','-Werror',
       '-DDYN_EXPERIMENT_COMPACT_SOURCES','-DDYN_EXPERIMENT_COMPACT_AST','-DDYN_EXPERIMENT_COMPACT_FIRST']
if a.sanitize: flags+=['-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-omit-frame-pointer']
exe=build/'first-unit'
subprocess.run([*shlex.split(os.environ.get('CC','cc')),*flags,'-I',str(ROOT/'src'),'-I',str(grammar/'src'),
    str(HERE/'first-unit.c'),*[str(ROOT/'src'/name) for name in ('source.c','source_tree.c','diagnostic.c','target.c')],
    str(grammar/'src/parser.c'),str(grammar/'src/scanner.c'),'-ltree-sitter','-o',str(exe)],check=True)
with tempfile.TemporaryDirectory(prefix='dyn-first-regression-') as tmp:
    files=[]
    for i,case in enumerate(json.loads((HERE/'first-regressions.json').read_text())):
        file=Path(tmp)/f'{i}.dyn';file.write_bytes(case['source'].encode());files.append(str(file))
    subprocess.run([str(exe),*files],check=True,timeout=60)
print('PASS compact-first no-tree source preparation, explicit fallback, depth policy, allocation failures, cancellation and revision invalidation')
