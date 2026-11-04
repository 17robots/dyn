#!/usr/bin/env python3
"""Native release arithmetic folds in range constants and wraps at runtime."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build/dyn')).resolve()
with tempfile.TemporaryDirectory(prefix='dyn-native-release-') as directory:
    root = Path(directory)
    source = root/'main.dyn'
    output = root/'program'
    # Typed return values force the emitter to respect narrow integer widths.
    cases = [('u8', '250 + 5', 255), ('i8', '60 + 67', 127),
             ('u64', '18446744073709551615 - 1', 18446744073709551614),
             ('i64', '(19 + 23) * 2', 84)]
    for ty, expression, expected in cases:
        source.write_text(f'fn value() {ty} {{ return {expression} }}\n'
                          f'fn main() {{ if value() != {expected} {{ #panic("constant folding") }} }}\n')
        subprocess.run([str(DYN), 'build', str(root), '--backend', 'native', '--release',
                        '--no-cache', '--quiet', '--output', str(output)], check=True)
        subprocess.run([str(output)], check=True)
    # Runtime overflow wraps at the type's width.
    source.write_text('''fn value(start: u8) u8 { return start + 10 }
fn main() { if value(250) != 4 { #panic("wrap") } }
''')
    subprocess.run([str(DYN), 'build', str(root), '--backend', 'native', '--release',
                    '--no-cache', '--quiet', '--output', str(output)], check=True)
    subprocess.run([str(output)], check=True)
print('PASS native release literal folding, integer boundaries and wrapping')
