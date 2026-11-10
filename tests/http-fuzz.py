#!/usr/bin/env python3
"""Fuzz HTTP framing, form decoding, path matching, header injection and HTML
escaping: debug (bounds-checked) and release. DYN_FUZZ_SCALE multiplies the
20000 cases per property for longer local runs."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SCALE = os.environ.get('DYN_FUZZ_SCALE', '1')
with tempfile.TemporaryDirectory(prefix='dyn-http-fuzz-') as temporary:
    for mode, scale in (('--debug', SCALE), ('--release', str(10 * int(SCALE)))):
        program = Path(temporary) / 'fuzz'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/http-fuzz'), mode, '--no-cache', '--quiet',
                        '--output', str(program)], check=True, timeout=300)
        result = subprocess.run([str(program), scale], capture_output=True, text=True, timeout=900)
        assert result.returncode == 0 and result.stdout == 'ok\n', result.stderr
print('PASS HTTP fuzz: framing prefixes, form round trip, path captures, header injection, escaping (debug/release)')
