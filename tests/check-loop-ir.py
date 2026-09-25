#!/usr/bin/env python3
"""Check optimized loops, allowing necessary overflow guards in arena setup."""
from pathlib import Path
import re
import sys
source = Path(sys.argv[1]).read_text()
if 'llvm.loop.isvectorized' not in source:
    raise SystemExit('expected benchmark loops to vectorize')
for function in re.finditer(r'^define\b[^\n]*\{\n(.*?)^}', source, re.M | re.S):
    blocks = {}
    current = 'entry'
    for line in function.group(1).splitlines():
        label = re.match(r'^([\w.$-]+):', line)
        if label:
            current = label.group(1)
        blocks.setdefault(current, []).append(line.split(';', 1)[0])
    successors = {name: set(re.findall(r'label %([\w.$-]+)', '\n'.join(lines)))
                  for name, lines in blocks.items()}
    for name, lines in blocks.items():
        if not any('with.overflow' in line for line in lines):
            continue
        pending = list(successors[name])
        seen = set()
        while pending:
            target = pending.pop()
            if target == name:
                raise SystemExit(f'expected range proof to remove loop overflow checks: {name}')
            if target not in seen:
                seen.add(target)
                pending.extend(successors.get(target, ()))
print('PASS vectorized loops without per-iteration overflow guards')
