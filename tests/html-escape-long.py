#!/usr/bin/env python3
"""html.text on long strings against a Python oracle: dense and sparse
specials at every position, through the eight-byte copy, the branch-free
word stores and the exact tail. Bytes past the output stay untouched
(debug/release)."""
import os
from pathlib import Path
import random
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
random.seed(0x48544d4c)
special = ['&', '<', '>', '"', "'"]
plain = ['a', 'Z', ' ', '0', '?', '=', ';', '#', '%', '\x00', 'é', '—', '😀']
cases = []
for length in list(range(0, 48)) + [63, 64, 65, 200, 1000]:
    for density in (0.0, 0.05, 0.3, 0.9):
        cases.append(''.join(random.choice(special) if random.random() < density else random.choice(plain)
                             for _ in range(length)))
cases.append('Tom & Jerry <b>said</b> "hi" — it\'s 5 > 3 & 2 < 4. ' * 3)
entities = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}


def literal(text):
    return '"' + ''.join('\\x%02x' % b for b in text.encode()) + '"'


source = ['use "std/html"', 'use "std/io"', 'use "std/fail"', '', 'fn show(text: []const u8) {', '  storage: [8192]u8',
          '  status: fail.Status', '  out := html.writer(&status, storage[..])', '  html.text(&out, text)', '  written := html.output(&out).bytes',
          '  untouched := true', '  for i in written.len..storage.len {', '    untouched = untouched && storage[i] == 0',
          '  }', '  io.println("{} {}", untouched, written)', '}', '', 'fn main() {']
source += [f'  show({literal(case)})' for case in cases]
source += ['}', '']
expected = ''.join('true ' + ''.join(entities.get(ch, ch) for ch in case) + '\n' for case in cases)
with tempfile.TemporaryDirectory(prefix='dyn-html-escape-long-') as temporary:
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
print(f'PASS html.text: {len(cases)} long strings match the Python oracle, nothing written past the output (debug/release)')
