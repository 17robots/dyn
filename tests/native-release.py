#!/usr/bin/env python3
"""Native release arithmetic preserves checked overflow and wrapping behavior."""
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
    cases = [('u8', '250 + 5', 255), ('u8', '#wrap(250 + 10)', 4),
             ('u8', '#wrap(1 - 4)', 253), ('u8', '#wrap(200 * 3)', 88),
             ('i8', '60 + 67', 127), ('i8', '#wrap(120 + 10)', -126),
             ('i8', '#wrap(100 * 2)', -56), ('u64', '18446744073709551615 - 1', 18446744073709551614),
             ('u64', '#wrap(18446744073709551615 + 2)', 1),
             ('i64', '(19 + 23) * 2', 84)]
    for ty, expression, expected in cases:
        source.write_text(f'fn value() {ty} {{ return {expression} }}\n'
                          f'fn main() {{ if value() != {expected} {{ #panic("constant folding") }} }}\n')
        subprocess.run([str(DYN), 'build', str(root), '--backend', 'native', '--release',
                        '--no-cache', '--quiet', '--output', str(output)], check=True)
        subprocess.run([str(output)], check=True)
    # Checked overflow must still panic, with deferred cleanup executed first.
    source.write_text('''use "std/io"
fn value() u8 { defer { _=io.println(io.stdout(), "cleanup") }
value:u8=250
return value + 10 }
fn main() { _=value() }
''')
    subprocess.run([str(DYN), 'build', str(root), '--backend', 'native', '--release',
                    '--no-cache', '--quiet', '--output', str(output)], check=True)
    result = subprocess.run([str(output)], capture_output=True, text=True)
    assert result.returncode != 0 and 'overflow.ok' in result.stderr, result
    assert result.stdout == 'cleanup\n', result
print('PASS native release literal folding, integer boundaries, wrapping and deferred cleanup')
