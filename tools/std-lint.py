#!/usr/bin/env python3
"""Flag std APIs that break the std standardization rules.

Checks every `pub fn` in std/:
- names ending in _into (rule 4: produce into an arena);
- a `name_size` or `name_count` next to a `name` that takes caller storage,
  the size-query companion of a caller-buffer form (rule 4);
- parameters named output or out with a pointer type (rule 3: return results);
- find functions returning isize (rule 2: a miss returns the length).

Exit status 1 lists each violation as path:line: message.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = re.compile(r'^pub fn (\w+)\((.*?)\)\s*(.*?)\s*\{?\s*$')


def check(path):
    problems = []
    names = {}
    lines = path.read_text().split('\n')
    for number, line in enumerate(lines, 1):
        match = DECLARATION.match(line)
        if match:
            names[match.group(1)] = number
    for name, number in names.items():
        line = lines[number - 1]
        _, parameters, result = DECLARATION.match(line).groups()
        if name.endswith('_into'):
            problems.append((number, f'{name}: caller-buffer form; take the arena first and drop _into'))
        for suffix in ('_size', '_count'):
            base = name[:-len(suffix)]
            if name.endswith(suffix) and base in names:
                base_parameters = DECLARATION.match(lines[names[base] - 1]).group(2)
                if re.search(r'\b(destination|storage)\s*:', base_parameters):
                    problems.append((number, f'{name}: size companion of {base}; size the output inside it'))
        if re.search(r'\b(output|out)\s*:\s*\*', parameters):
            problems.append((number, f'{name}: out parameter; return a {{value, ok}} result'))
        if name.startswith('find') and result.strip() == 'isize':
            problems.append((number, f'{name}: returns isize; return usize and the length on a miss'))
    return problems


failures = 0
for path in sorted((ROOT / 'std').rglob('*.dyn')):
    for number, message in check(path):
        print(f'{path.relative_to(ROOT)}:{number}: {message}')
        failures += 1
if failures:
    sys.exit(1)
print('PASS std lint: no _into forms, size companions, out parameters or -1 positions')
