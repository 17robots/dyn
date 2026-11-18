#!/usr/bin/env python3
"""Errors that point at the fix: a misspelled or private module member, an
import written as in other languages, and a typed array literal."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
CASES = (
    ('use "std/strings"\n\nfn main() {\n  _ = strings.formatt\n}\n', "'strings' has no pub member 'formatt'; did you mean 'strings.format'?"),
    ('use "std/fmt"\n\nfn main() {\n  _ = fmt.Bufer{}\n}\n', "did you mean 'fmt.Buffer'?"),
    ('use "std/fmt"\n\nfn main() {\n  _ = fmt.zzzzzzzz\n}\n', "'fmt' has no pub member 'zzzzzzzz'\n"),
    ('use "std/fmt"\n\nfn main() {\n  _ = fmt.f64_decimal_into\n}\n', "'fmt.f64_decimal_into' is not pub"),
    ('import io\n\nfn main() {\n}\n', 'Dyn imports a module with use, as in use "std/io"'),
    ('fn main() {\n  sizes := [3]usize{ 1, 2, 3 }\n  _ = sizes\n}\n', 'write an array literal as [a, b, c] and give the type to the name'),
    ('use "std/fs"\nuse "std/mem"\nuse "std/fail"\n\nfn main() {\n  a := mem.arena_alloc(0)\n  status: fail.Status\n'
     '  _ = fs.list_entries(a, &status, ".")\n}\n', "'fs' has no pub member 'list_entries'; related: fs.list"),
    ('use "std/fs"\nuse "std/fail"\n\nfn main() {\n  status: fail.Status\n  fs.create_dir_all(&status, "x")\n}\n',
     "'fs' has no pub member 'create_dir_all': Dyn calls it fs.make_directory(&status, path, 0o755)"),
    ('use "std/strings"\n\nfn main() {\n  _ = strings.equal("a", "b")\n}\n',
     "'strings.equal' was removed: use bytes.equal(a, b) from std/bytes"),
    # Neighboring arguments that each fit the other's place are reported as
    # swapped, with the swap as a suggestion; a plain mismatch is not.
    ('use "std/fs"\nuse "std/mem"\nuse "std/fail"\n\nfn main() {\n  a := mem.arena_alloc(0)\n  status: fail.Status\n'
     '  _ = fs.read_all(&status, a, "x", 10)\n}\n',
     "function arguments 1 and 2 look swapped (expected *Arena, *Status; found *Status, *Arena)\n"
     " 8 |   _ = fs.read_all(&status, a, \"x\", 10)\n   |                   ^~~~~~~~~~\n"
     " suggestion: replace '&status, a' with 'a, &status'"),
    ('fn pair(n: i32, name: []const u8) {\n  _ = n\n  _ = name\n}\n\nfn main() {\n  name: []const u8 = "x"\n  pair(name, name)\n}\n',
     "function argument type mismatch (expected i32, found []const u8)"),
)
with tempfile.TemporaryDirectory(prefix='dyn-diagnostic-hints-') as temporary:
    for index, (source, message) in enumerate(CASES):
        project = Path(temporary) / f'case{index}'
        project.mkdir()
        (project / 'main.dyn').write_text(source)
        checked = subprocess.run([DYN, 'check', str(project)], capture_output=True, text=True, timeout=60)
        assert checked.returncode != 0 and message in checked.stderr, (source, checked.stderr)
    # A variable named import is still a variable.
    project = Path(temporary) / 'variable'
    project.mkdir()
    (project / 'main.dyn').write_text('import: i32 = 5\n\nfn main() {\n  _ = import\n}\n')
    checked = subprocess.run([DYN, 'check', str(project)], capture_output=True, text=True, timeout=60)
    assert checked.returncode == 0, checked.stderr
print('PASS diagnostic hints: member suggestions, related members, moved functions, private members, use instead of import, array literals, swapped arguments')
