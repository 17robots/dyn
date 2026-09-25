#!/usr/bin/env python3
"""Fetch the immutable external grammar dependency; never vendor it into Dyn."""
import json
import os
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parents[1]
if os.environ.get('TS_DIR'):
    target = Path(os.environ['TS_DIR']).resolve()
    if not all((target/name).is_file() for name in ('src/parser.c','src/scanner.c')):
        raise SystemExit('TS_DIR must contain generated parser.c and scanner.c')
    print('Using explicit grammar checkout:',target)
else:
    lock = json.loads((ROOT/'grammar.lock.json').read_text())
    target = ROOT/'build/deps/tree-sitter-dyn'
    if not target.exists():
        target.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['git','clone','--no-checkout',lock['repository'],str(target)],check=True)
        subprocess.run(['git','-C',str(target),'fetch','--depth','1','origin',lock['revision']],check=True)
        subprocess.run(['git','-C',str(target),'checkout','--detach',lock['revision']],check=True)
    revision = subprocess.check_output(['git','-C',str(target),'rev-parse','HEAD'],text=True).strip()
    dirty = subprocess.check_output(['git','-C',str(target),'status','--porcelain'],text=True).strip()
    if revision != lock['revision'] or dirty:
        raise SystemExit('Managed grammar checkout differs from grammar.lock.json; remove build/deps/tree-sitter-dyn and rerun just deps, or use TS_DIR explicitly')
    print('External grammar:',revision)
