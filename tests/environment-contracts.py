#!/usr/bin/env python3
"""Verify environment values crossing the adapter's read-buffer boundary."""
import os
from pathlib import Path
import subprocess

compiler = str(Path(os.environ.get('DYN', './build/dyn')).resolve())
output = Path('build/environment-contracts').resolve()
subprocess.run([compiler, 'build', 'tests/environment-contracts', '--no-cache',
                '--quiet', '--output', str(output)], check=True)
env = dict(os.environ)
env.pop('DYN_ENV_NOT_PRESENT', None)
env.update(DYN_ENV_PADDING='p' * 4090, DYN_ENV_LONG='x' * 9000, DYN_ENV_EMPTY='')
subprocess.run([str(output)], env=env, check=True, timeout=10)
