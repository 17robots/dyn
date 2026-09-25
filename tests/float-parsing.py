#!/usr/bin/env python3
"""Compare decimal conversion with Python's correctly rounded binary64 parser."""
import os
import decimal
import random
import struct
import subprocess
import tempfile
from pathlib import Path
random.seed(42)
values = ['0.1', '1.2345678901234567', '2.2250738585072014e-308', '4.9406564584124654e-324',
          '2.4703282292062327e-324', '2.4703282292062328e-324', '1.7976931348623157e308',
          '1.7976931348623159e308', '-0', '9007199254740993', '1.00000000000000011102230246251565404236316680908203125',
          '1.00000000000000011102230246251565404236316680908203125000000001']
with decimal.localcontext() as context:
    context.prec = 2000
    halfway = format(decimal.Decimal(2) ** -1075, 'f')
    values += [halfway, halfway + '0' * 100 + '1',
               '1.' + '0' * 999 + '1', '9' * 1000 + 'e-999',
               '0.' + '0' * 1200 + '1e1201']
for _ in range(100):
    bits = random.randrange(0x7ff0000000000000)
    values.append(repr(struct.unpack('<d', struct.pack('<Q', bits))[0]))
for _ in range(150):
    digits = ''.join(str(random.randrange(10)) for _ in range(random.randrange(1, 80)))
    values.append(digits + 'e' + str(random.randrange(-380, 310) - len(digits)))
with tempfile.TemporaryDirectory(prefix='dyn-float-parsing-') as folder:
    root = Path(folder)
    lines = ['use "std/strings"', 'fn main() {', 'value: f64 = 0.0', 'expected: u64 = 0']
    for i, value in enumerate(values):
        bits = struct.unpack('<Q', struct.pack('<d', float(value)))[0]
        lines += [f'expected = {bits}', f'if !strings.parse_f64("{value}", &value) || #bitcast(u64) value != expected {{ #panic("decimal case {i}: {value}") }}']
    lines.append('}')
    (root / 'main.dyn').write_text('\n'.join(lines))
    output = root / 'program'
    for mode in [[], ['--release']]:
        subprocess.run([os.environ.get('DYN', './build/dyn'), 'build', folder, '--quiet', '--no-cache', '--output', str(output), *mode], check=True)
        subprocess.run([str(output)], check=True)
