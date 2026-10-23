#!/usr/bin/env python3
"""std/mmio links on every native target and performs real accesses."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
TARGETS = ('x86_64-linux', 'aarch64-linux', 'riscv64-linux', 'riscv64-none', 'riscv32-none', 'thumbv7em-none', 'x86_64-macos',
           'aarch64-macos', 'x86_64-windows', 'aarch64-windows')
with tempfile.TemporaryDirectory(prefix='dyn-mmio-') as temporary:
    for release in (False, True):
        mode = ['--release'] if release else []
        for target in TARGETS:
            subprocess.run([DYN, 'build', str(ROOT / 'tests/mmio'), '--target', target, '--quiet', '--no-cache',
                            '--output', str(Path(temporary) / target), *mode], check=True, timeout=120)
        host = Path(temporary) / 'host'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/mmio'), '--quiet', '--no-cache', '--output', str(host), *mode],
                       check=True, timeout=120)
        subprocess.run([str(host)], check=True, timeout=30)
print('PASS std/mmio on every native target (debug/release); device access runs on QEMU in bare-metal.py')
