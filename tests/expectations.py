#!/usr/bin/env python3
"""Diagnostic expectations written in the source they test.

Each tests/expect/*.dyn file is one program. A comment `// error: TEXT` on a
line expects an error on that line whose message contains TEXT; several
comments on one line expect several errors. `// error@+N: TEXT` expects it N
lines below, for lines that cannot hold a comment. Every error the compiler
reports must be expected, and every expectation must be met.

Run one file with: tests/expectations.py tests/expect/NAME.dyn"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())
PATTERN = re.compile(r'//\s*(error|note)(@\+\d+)?:\s*(.*?)\s*(?=//\s*(?:error|note)|$)')


def expectations(path):
    expected = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        for severity, offset, text in PATTERN.findall(line):
            target = number + (int(offset[2:]) if offset else 0)
            expected.append((target, severity, text))
    return expected


def check(path):
    result = subprocess.run([DYN, 'check', '--diagnostics', 'json', str(path)],
                            capture_output=True, text=True, timeout=60,
                            env={**os.environ, 'DYN_SDK': str(ROOT)})
    reported = []
    for line in result.stderr.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            return [f'{path.name}: unparsed compiler output: {line}']
        reported.append((item['range']['start']['line'], item['severity'], item['message']))
    problems = []
    unmatched = list(reported)
    for line, severity, text in expectations(path):
        match = next((r for r in unmatched if r[0] == line and r[1] == severity and text in r[2]), None)
        if match:
            unmatched.remove(match)
        else:
            problems.append(f'{path.name}:{line}: expected {severity} containing "{text}"')
    for line, severity, message in unmatched:
        if severity == 'error':
            problems.append(f'{path.name}:{line}: unexpected {severity}: {message}')
    if not expectations(path) and result.returncode != 0:
        problems.append(f'{path.name}: expected a clean check, got exit {result.returncode}')
    return problems


files = [Path(a) for a in sys.argv[1:]] or sorted((ROOT / 'tests/expect').glob('*.dyn'))
problems = [problem for path in files for problem in check(path)]
for problem in problems:
    print(problem)
if problems:
    raise SystemExit(1)
print(f'PASS diagnostic expectations ({len(files)} files)')
