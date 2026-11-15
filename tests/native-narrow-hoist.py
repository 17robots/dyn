#!/usr/bin/env python3
"""32-bit ALU forms and ROR on x86-64 and AArch64 (ssa_narrow32), and pure leaf calls
expanded from anywhere in a statement (inline_hoist): release output equals
debug output, and release code uses ROR for the rotate helpers."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-narrow-hoist-') as temporary:
    work = Path(temporary)
    outputs = []
    # The helpers mean to wrap, so the debug build drops overflow checks.
    for flags in (['--debug', '--no-check-overflow'], ['--release'], ['--release', '--opt-level', '3']):
        program = work / 'program'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/native-narrow-hoist'), *flags, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=180)
        outputs.append(subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=30).stdout)
    assert outputs[0] == outputs[1] == outputs[2], outputs
    assert outputs[0].count('\n') == 2 and outputs[0].split('\n')[1].startswith('true '), outputs[0]
    if platform.machine() in ('x86_64', 'AMD64'):
        listing = work / 'program.s'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/native-narrow-hoist'), '--release', '--quiet', '--no-cache',
                        '--emit-asm', '--output', str(listing)], check=True, timeout=180)
        text = (work / 'program.s.s').read_text() if (work / 'program.s.s').exists() else listing.read_text()
        main = text[text.index('_main"'):] if '_main"' in text else text
        assert ': ror ' in main, 'release main uses ROR'
    # AArch64 W-register forms and EXTR, under qemu when it is installed.
    qemu = shutil.which('qemu-aarch64')
    if qemu:
        program = work / 'program-a64'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/native-narrow-hoist'), '--release', '--target', 'aarch64-linux',
                        '--quiet', '--no-cache', '--output', str(program)], check=True, timeout=180)
        result = subprocess.run([qemu, str(program)], capture_output=True, text=True, check=True, timeout=60).stdout
        assert result == outputs[0], (result, outputs[0])
print('native narrow hoist ok')
