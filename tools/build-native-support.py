#!/usr/bin/env python3
"""Compile portable freestanding runtime support with the independent compiler."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--compiler', required=True, type=Path)
parser.add_argument('--target', required=True)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
args.output.parent.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='dyn-support-', dir=args.output.parent) as directory:
    output = Path(directory)/'support'
    subprocess.run([str(args.compiler.resolve()), 'build', str(ROOT/'runtime/support'),
                    '--backend', 'native', '--release', '--shared', '--emit-object',
                    '--no-link', '--runtime-support', '--target', args.target,
                    '--output', str(output), '--quiet'], check=True)
    os.replace(output.with_suffix('.o'), args.output)
