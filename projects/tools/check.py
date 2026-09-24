#!/usr/bin/env python3
"""Check every example module using a supplied or installed Dyn SDK."""
import os
from pathlib import Path
import subprocess
root = Path(__file__).resolve().parents[1]
dyn = os.environ.get('DYN', 'dyn')
folders = sorted({p.parent for top in root.iterdir() if top.is_dir() and not top.name.startswith('.') and top.name not in ('build', 'tools') for p in top.rglob('*.dyn')})
for folder in folders:
    flags = ['--target', 'wasm32-browser'] if folder in (root/'browser-canvas', root/'browser-video') else []
    if folder == root/'wasi-hello': flags = ['--target', 'wasm32-wasi']
    subprocess.run([dyn, 'check', str(folder), '--quiet', '--no-cache', *flags], check=True)
print(f'PASS {len(folders)} project modules')
