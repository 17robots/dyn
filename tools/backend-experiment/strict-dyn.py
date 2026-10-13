#!/usr/bin/env python3
"""Compiler wrapper for test runs: native-eligible builds require native emission.

The default --backend auto silently falls back to LLVM. Running the regression
suite through this wrapper (DYN=.../strict-dyn.py, DYN_REAL=build/dyn) turns any
unsupported program into a visible failure instead.
"""
import os
from pathlib import Path
import sys

dyn = os.environ.get('DYN_REAL') or str(Path(__file__).resolve().parents[2]/'build/dyn')
args = sys.argv[1:]
llvm_only = {'--release', '--shared', '--emit-ir', '--emit-asm', '--backend', '--cpu',
             '--opt-remarks', '--sample-profile', '--opt-level'}
target = 'x86_64-linux'
if '--target' in args and args.index('--target') + 1 < len(args):
    target = args[args.index('--target') + 1]
if args and args[0] in ('build', 'run') and not llvm_only & set(args) and target == 'x86_64-linux':
    args = [args[0], '--backend', 'native', *args[1:]]
os.execv(dyn, [dyn, *args])
