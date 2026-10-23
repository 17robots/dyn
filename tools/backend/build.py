#!/usr/bin/env python3
"""Build the standalone native backend and its unit tests against the frontend."""
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BUILD = Path(os.environ.get('BUILD', ROOT / 'build')).resolve()
BUILD.mkdir(parents=True, exist_ok=True)
sources = ['frontend.c', 'ast.c', 'sema.c', 'sema_globals.c', 'source.c',
           'source_tree.c', 'diagnostic.c', 'target.c', 'ir.c', 'parser.c', 'snapshot.c']
command = [*shlex.split(os.environ.get('CC', 'cc')), '-std=c11', '-O2', '-g',
           '-Wall', '-Wextra', '-Wpedantic', '-Werror', '-D_POSIX_C_SOURCE=200809L',
           *shlex.split(os.environ.get('CFLAGS', '')),
           '-I' + str(ROOT / 'src'),
           str(ROOT / 'src/backend' / 'driver.c'),
           str(ROOT / 'src/backend' / 'dwarf.c'),
           *(str(ROOT / 'src' / name) for name in sources),
           '-pthread', '-o', str(BUILD / 'scalar-backend')]
subprocess.run(command, check=True)

# The native unit exercises multiple emissions in one process and concurrent calls.
unit = command.copy()
unit[unit.index(str(ROOT / 'src/backend' / 'driver.c'))] = str(ROOT / 'src/backend' / 'reentrant-unit.c')
unit[-1] = str(BUILD / 'backend-reentrant-test')
subprocess.run(unit, check=True)
subprocess.run([str(BUILD / 'backend-reentrant-test')], check=True)

output_unit = [*shlex.split(os.environ.get('CC', 'cc')), '-std=c11', '-O2', '-g',
               '-Wall', '-Wextra', '-Wpedantic', '-Werror',
               *shlex.split(os.environ.get('CFLAGS', '')),
               str(ROOT / 'src/backend' / 'output-unit.c'), '-pthread',
               '-o', str(BUILD / 'backend-output-test')]
subprocess.run(output_unit, check=True)
subprocess.run([str(BUILD / 'backend-output-test')], check=True)
