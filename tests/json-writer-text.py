#!/usr/bin/env python3
"""json.text against a Python oracle: random strings with control bytes,
quotes, backslashes and multi-byte UTF-8 at every position and length,
across the eight-byte scan and its byte-by-byte tail (debug/release)."""
import os
from pathlib import Path
import random
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
random.seed(0x4a534f4e)
pieces = ['a', 'b', 'z', ' ', '0', '"', '\\', '\n', '\r', '\t', '\x01', '\x1f', '\x7f', 'é', '€', '😀', '<', '/']
cases = []
for length in range(0, 40):
    for _ in range(6):
        cases.append(''.join(random.choice(pieces) for _ in range(length)))
cases += ['x' * n + '"' for n in range(20)] + ['\x00' + 'y' * n for n in range(20)]


def escape(text):
    out = []
    for ch in text:
        if ch == '"': out.append('\\"')
        elif ch == '\\': out.append('\\\\')
        elif ch == '\n': out.append('\\n')
        elif ch == '\r': out.append('\\r')
        elif ch == '\t': out.append('\\t')
        elif ord(ch) < 0x20: out.append('\\u00%02x' % ord(ch))
        else: out.append(ch)
    return '"' + ''.join(out) + '"'


def literal(text):
    return '"' + ''.join('\\x%02x' % b for b in text.encode()) + '"'


source = ['use "std/encoding/json"', 'use "std/io"', 'use "std/fail"', '', 'fn show(text: []const u8) {', '  storage: [512]u8',
          '  status: fail.Status', '  out := json.writer(&status, storage[..])', '  json.text(&out, text)', '  io.println("{}", json.output(&out))', '}', '',
          'fn main() {']
source += [f'  show({literal(case)})' for case in cases]
source += ['}', '']
expected = ''.join(escape(case) + '\n' for case in cases)
with tempfile.TemporaryDirectory(prefix='dyn-json-writer-text-') as temporary:
    work = Path(temporary)
    (work / 'project').mkdir()
    (work / 'project' / 'main.dyn').write_text('\n'.join(source))
    for mode in ('--debug', '--release'):
        subprocess.run([DYN, 'build', str(work / 'project'), mode, '--quiet', '--no-cache', '--output', str(work / 'program')],
                       check=True, timeout=300)
        output = subprocess.run([str(work / 'program')], capture_output=True, check=True, timeout=60).stdout.decode()
        for got, want, case in zip(output.split('\n'), expected.split('\n'), cases):
            assert got == want, (mode, repr(case), got, want)
        assert output == expected
print(f'PASS json.text: {len(cases)} strings match the Python oracle (debug/release)')
