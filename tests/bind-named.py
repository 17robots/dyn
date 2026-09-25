#!/usr/bin/env python3
"""Named C typedef records must survive binding generation."""
from pathlib import Path
import runpy

generate = runpy.run_path('tools/dyn-bind.py')['generate']
source = 'typedef struct Record { int x; unsigned char flag; } Record;\nenum Kind { First };\nint visit(const Record *value);\n'
output = generate(source)
assert 'pub struct Record {\n  x: i32,\n  flag: u8,\n}' in output, output
assert 'value: *const Record' in output, output
source = 'typedef struct Tag { int value; } Alias;\nint visit(const Alias *value);\n'
output = generate(source)
assert 'pub struct Tag {' in output and 'pub type Alias = Tag' in output, output

# LLP64 Windows long must use the target-aware SDK alias, not pointer width.
output = generate('long count(unsigned long value);\nlong long wide(unsigned long long value);\n')
assert 'value: c.unsigned_long) c.long' in output, output
assert 'value: u64) i64' in output, output
output = generate('#define OCTAL 010u\nenum Mode { First = 010, Next };\n')
assert 'OCTAL: u64 = 8' in output and 'First: Mode = 8' in output and 'Next: Mode = 9' in output, output
output = generate('enum Flags { First = 1 << 2, Next };\n#define BAD 09\n')
assert 'pub type Flags' not in output and '// enum Flags:' in output and '// macro BAD:' in output, output
output = generate('void visit(void (*callback)(void));\n')
assert 'callback: *fn()' in output, output
print('PASS named records, target-aware C long, octal and unsupported enum expressions')
