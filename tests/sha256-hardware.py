#!/usr/bin/env python3
"""SHA-256 on x86-64 uses the CPU's SHA instructions when CPUID reports them
(runtime/native_sha256_x86_64.S) and the Dyn code otherwise. Both give the
hashlib digests: the host runs one path, and qemu-x86_64 as a Haswell (no
SHA) and as max (SHA) runs each on purpose."""
import hashlib
import hmac
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
expected = '\n'.join([
    hashlib.sha256(b'abc').hexdigest(),
    hashlib.sha256(bytes((i * 7) & 255 for i in range(1000))).hexdigest(),
    hmac.new(b'key', b'The quick brown fox jumps over the lazy dog', hashlib.sha256).hexdigest(),
    hashlib.pbkdf2_hmac('sha256', b'password', b'salt', 4096).hex(),
]) + '\n'
with tempfile.TemporaryDirectory(prefix='dyn-sha256-hardware-') as temporary:
    program = Path(temporary) / 'program'
    runs = 0
    for mode in ('--debug', '--release'):
        subprocess.run([DYN, 'build', str(ROOT / 'tests/sha256-hardware'), mode, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=180)
        commands = [[str(program)]]
        qemu = shutil.which('qemu-x86_64')
        if qemu and platform.machine() in ('x86_64', 'AMD64'):
            commands += [[qemu, '-cpu', 'Haswell', str(program)], [qemu, '-cpu', 'max', str(program)]]
        for command in commands:
            output = subprocess.run(command, capture_output=True, text=True, check=True, timeout=120).stdout
            assert output == expected, (mode, command[:3], output)
            runs += 1
print(f'PASS SHA-256 with and without SHA instructions: {runs} runs match hashlib')
