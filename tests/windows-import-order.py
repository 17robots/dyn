#!/usr/bin/env python3
"""The Windows loader fills import address slot n with the function named in
lookup entry n, so each start file must list its imports in the same order in
both tables. A swap calls the wrong function, which no Linux test sees."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
for name in ('windows_x86_64_start.S', 'windows_aarch64_start.S'):
    lines = (ROOT / 'runtime' / name).read_text().split('\n')
    lookup = [line.split()[1] for line in lines if re.match(r'^\s+thunk \w', line)]
    address = [line.split()[1] for line in lines if re.match(r'^iat \w', line)]
    assert lookup == address, (name, next((i, a, b) for i, (a, b) in enumerate(zip(lookup, address)) if a != b))
print('PASS Windows import lookup and address tables list imports in the same order')
