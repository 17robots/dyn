#!/usr/bin/env python3
"""Audit compact raw-depth upper bounds against the pinned Tree-sitter grammar."""
import argparse,json,os,runpy,shlex,subprocess,tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--sanitize',action='store_true')
p.add_argument('--corpus',type=Path,action='append',default=[])
a=p.parse_args()
grammar=Path(os.environ.get('TS_DIR',ROOT/'build/deps/tree-sitter-dyn')).resolve()
runpy.run_path(str(HERE/'grammar-pin.py'))['verify'](grammar)
build=Path(os.environ.get('BUILD',ROOT/'build')).resolve()/'parser-experiment-work'
build.mkdir(parents=True,exist_ok=True)
flags=['-std=c11','-O2','-g','-Wall','-Wextra','-Wpedantic','-Werror']
if a.sanitize: flags+=['-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-omit-frame-pointer']
exe=build/'depth-unit'
subprocess.run([*shlex.split(os.environ.get('CC','cc')),*flags,'-I',str(grammar/'src'),
    *map(str,[HERE/'depth-unit.c',HERE/'parser.c',HERE/'snapshot.c',grammar/'src/parser.c',grammar/'src/scanner.c']),
    '-ltree-sitter','-o',str(exe)],check=True)
with tempfile.TemporaryDirectory(prefix='dyn-depth-') as tmp:
    fixtures=[]
    for i,case in enumerate(json.loads((HERE/'source-cases.json').read_text())):
        file=Path(tmp)/f'{i}.dyn';file.write_text(case['source']);fixtures.append(file)
    corpus=sorted({file.resolve() for root in a.corpus for file in root.rglob('*.dyn')})
    subprocess.run([str(exe),*map(str,[*fixtures,*corpus])],check=True,timeout=120)
