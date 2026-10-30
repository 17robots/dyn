#!/usr/bin/env python3
"""Batch syntax errors come from the handwritten parser, which recovers per statement and declaration."""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())

CASES = {
    'missing-operand': ('fn main() {\n  x := 1 +\n}\n', '3:1: error: expected expression, found \'}\' [range 3:1-3:2]'),
    'unclosed-block': ('fn main() {\n  if true {\n}\n', '4:1: error: expected \'}\', found end of file [range 4:1-4:1]'),
    'unclosed-call': ('fn main() {\n  foo(1, 2\n  bar()\n}\n', '3:3: error: expected \')\', found \'bar\' [range 3:3-3:6]'),
    'missing-parameter': ('fn f(a: i32, -> i32 { return a }\nfn main() {}\n',
                          '1:14: error: expected identifier, found \'->\' [range 1:14-1:16]'),
    'unterminated-string': ('fn main() {\n  x := "abc\n}\n', '2:8: error: unterminated literal [range 2:8-2:9]'),
    'stray-character': ('fn main() {\n  x := 1;\n}\n', '2:9: error: unexpected character \';\' [range 2:9-2:10]'),
    'invisible-character': ('fn main() {\n  return \u2028\n}\n', '2:10: error: unexpected character U+2028 [range 2:10-2:13]'),
    'trailing-expression': ('fn main() {\n  return 1\n  2\n}\n', '3:3: error: expression is not a statement [range 3:3-3:4]'),
    # Spans cover the type itself, not the `: ` before it (editors underline this range).
    'unknown-parameter-type': ('fn f(app: *App) {\n}\nfn main() {}\n', '1:11: error: unknown type in parameter [range 1:11-1:15]'),
}

with tempfile.TemporaryDirectory(prefix='dyn-syntax-diagnostics-') as temporary:
    root = Path(temporary)
    for name, (text, expected) in CASES.items():
        directory = root/name
        directory.mkdir()
        (directory/'main.dyn').write_text(text)
        for command in ('check', 'build'):
            result = subprocess.run([DYN, command, str(directory), '--no-cache', '--output', str(directory/'out')]
                                    if command == 'build' else [DYN, command, str(directory)],
                                    capture_output=True, text=True, timeout=60)
            errors = [line for line in result.stderr.splitlines() if 'error:' in line]
            assert result.returncode == 1, (name, command, result.returncode, result.stderr)
            assert len(errors) == 1 and errors[0].endswith('main.dyn:' + expected), (name, command, result.stderr)
            assert not (directory/'out').exists(), (name, command)

    # Recovery resumes at the next statement or declaration and reports each error.
    several = root/'several'
    several.mkdir()
    (several/'main.dyn').write_text('fn main() {\n  x := (1 +\n  y := 2\n  foo(y\n}\nstruct P { x: i32 y: i32 }\nfn ok() {}\n')
    result = subprocess.run([DYN, 'check', str(several)], capture_output=True, text=True, timeout=60)
    errors = [line.split('main.dyn:', 1)[1] for line in result.stderr.splitlines() if 'error:' in line]
    assert result.returncode == 1 and errors == [
        "3:5: error: expected ')', found ':=' [range 3:5-3:7]",
        "5:1: error: expected ')', found '}' [range 5:1-5:2]",
        "6:19: error: expected '}', found 'y' [range 6:19-6:20]"], result.stderr
    (several/'main.dyn').write_text('fn main() {\n' + '  x := )\n' * 30 + '}\n')
    result = subprocess.run([DYN, 'check', str(several)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 1 and result.stderr.count('error:') == 20, result.stderr

    # A broken imported module is reported at its own path; the importer is never analyzed.
    imported = root/'imported'
    (imported/'util').mkdir(parents=True)
    (imported/'main.dyn').write_text('use "util"\nfn main() { util.f() }\n')
    (imported/'util/util.dyn').write_text('pub fn f() {\n  x := (1 +\n}\n')
    result = subprocess.run([DYN, 'check', str(imported)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 1, result.stderr
    assert result.stderr.strip().endswith("util/util.dyn:3:1: error: expected expression, found '}' [range 3:1-3:2]"), result.stderr
    assert result.stderr.count('error:') == 1, result.stderr

print('PASS syntax diagnostics: handwritten parser messages, spans, build refusal and imported modules')
