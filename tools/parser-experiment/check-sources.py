#!/usr/bin/env python3
"""Qualify prepared compact sources and unchanged recovery import readers."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--sanitize', action='store_true')
args = parser.parse_args()
grammar = Path(os.environ.get('TS_DIR', ROOT/'build/deps/tree-sitter-dyn')).resolve()
build = Path(os.environ.get('BUILD', ROOT/'build')).resolve()/'parser-experiment-work'
build.mkdir(parents=True, exist_ok=True)
flags = ['-std=c11', '-D_POSIX_C_SOURCE=200809L', '-Wall', '-Wextra', '-Wpedantic', '-Werror', '-O2', '-g']
if args.sanitize:
    flags += ['-fsanitize=address,undefined','-fno-sanitize-recover=all', '-fno-omit-frame-pointer']
for compact in (False, True):
    exe = build/('source-consumers-compact' if compact else 'source-consumers-default')
    subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), *flags,
        *(['-DDYN_EXPERIMENT_COMPACT_SOURCES'] if compact else []),
        '-I', str(ROOT/'src'), '-I', str(grammar/'src'), str(HERE/'source-consumers-unit.c'),
        *[str(ROOT/'src'/name) for name in ('source.c', 'source_tree.c', 'diagnostic.c', 'target.c')],
        str(grammar/'src/parser.c'), str(grammar/'src/scanner.c'), '-ltree-sitter', '-o', str(exe)], check=True)
    subprocess.run([exe], check=True, timeout=60)
