#!/usr/bin/env python3
"""Type patterns, comparison chains, generic literals and adapting constants,
with the errors for mixed bitwise comparisons, ambiguous chains and `is`."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
ERRORS = {
    'fn main() {\n  f: u32 = 1\n  if f & 1 == 0 { }\n}\n':
        'mixing a bitwise operator with a comparison needs parentheses',
    'fn main() {\n  a := 1\n  b := 2\n  if a < b > 0 { }\n}\n':
        'only <, <= or >, >= chains in one direction',
    'fn main() {\n  a := true\n  if a == a == a { }\n}\n':
        '== and != do not chain',
    'fn f() i32 { return 1 }\nfn main() {\n  if 0 < f() < 2 { }\n}\n':
        "chained comparison's middle operand must be a name, field or literal",
    'fn f(v: any) {\n  case v {\n    is i32 => { }\n    _ => { }\n  }\n}\nfn main() { f(true) }\n':
        'type patterns do not use `is`',
    'const BIG := 300\nfn main() {\n  x: u8 = BIG\n  _ = x\n}\n':
        'integer literal is not representable in expected type',
}
with tempfile.TemporaryDirectory(prefix='dyn-language-forms-') as temporary:
    for name, flags in (('debug', ['--debug']), ('release', ['--release', '--opt-level', '3'])):
        program = Path(temporary) / name
        subprocess.run([DYN, 'build', str(ROOT / 'tests/language-forms'), *flags, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=120)
        result = subprocess.run([str(program)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0 and result.stdout == 'ok\n', (name, result)
    for index, (source, message) in enumerate(ERRORS.items()):
        project = Path(temporary) / f'error-{index}'
        project.mkdir()
        (project / 'main.dyn').write_text(source)
        result = subprocess.run([DYN, 'check', str(project)], capture_output=True, text=True, timeout=60)
        assert result.returncode != 0 and message in result.stderr, (source, result.stderr)
    # One-statement blocks written on one line keep their line.
    result = subprocess.run([DYN, 'fmt', '--check', str(ROOT / 'tests/language-forms')],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result
print('PASS language forms')
