#!/usr/bin/env python3
"""std/crypto/blake2b against hashlib, and std/crypto/password Argon2id
against the RFC 9106 test vector and, when installed, the reference argon2
command-line tool."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())

with tempfile.TemporaryDirectory(prefix='dyn-argon2-') as temporary:
    program = Path(temporary) / 'argon2'
    subprocess.run([DYN, 'build', str(ROOT / 'tests/argon2-results'), '--release', '--quiet', '--no-cache',
                    '--output', str(program)], check=True, timeout=180)
    run = lambda *arguments: subprocess.run([str(program), *map(str, arguments)], check=True, capture_output=True,
                                            text=True, timeout=60).stdout.strip()
    assert run('rfc') == '0d640df58d78766c08c037a34a8b53c9d01ef0452d75b65eb52520e96b01e659'
    for length, key, text in ((64, '', ''), (64, '', 'abc'), (32, 'secret key', 'x' * 1000), (1, 'k', 'y' * 128),
                              (20, '', 'z' * 129), (64, 'k' * 64, 'é' * 300)):
        want = hashlib.blake2b(text.encode(), digest_size=length, key=key.encode()).hexdigest()
        assert run('blake2b', length, key, text) == want, (length, key)
    reference = shutil.which('argon2')
    cases = [('hunter2', 'saltsaltsalt', 64, 2, 1, 32), ('correct horse', 'somesaltvalue', 256, 3, 2, 16),
             ('x', '0123456789abcdef', 32, 1, 4, 64), ('pässwörd', 'salt1234', 1024, 1, 1, 100),
             ('p', 'eightbyt', 4096, 2, 3, 32)]
    for password, salt, memory, iterations, lanes, length in cases:
        encoded = run(password, salt, memory, iterations, lanes, length)
        if reference:
            # The CLI takes memory as a power of two with -m, or KiB with -k.
            want = subprocess.run([reference, salt, '-id', '-t', str(iterations), '-k', str(memory), '-p', str(lanes),
                                   '-l', str(length), '-e'], input=password.encode(), capture_output=True,
                                  check=True).stdout.decode().strip()
            assert encoded == want, (encoded, want)
print('argon2 ok' + ('' if shutil.which('argon2') else ' (reference CLI not installed)'))
