#!/usr/bin/env python3
"""TypeInfo, TypeMember and TypeKind are the builtin types #typeof returns.
Every module reserves them, with or without reflection, and #typeof uses only
the compiler's own declarations."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())

def check(files):
    with tempfile.TemporaryDirectory(prefix='dyn-reflection-names-') as temporary:
        for name, text in files.items():
            path = Path(temporary) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return subprocess.run([DYN, 'run', temporary], capture_output=True, text=True, timeout=180)

for owner, declaration in (('main.dyn', 'struct TypeInfo { label: []const u8 }'),
                           ('other/other.dyn', 'pub enum TypeKind { A, B }'),
                           ('other/other.dyn', 'pub struct TypeMember { x: i32 }')):
    files = {'main.dyn': 'use "std/io"\nuse "./other"\n\nfn main() {\n  io.println("{}", other.size())\n}\n',
             'other/other.dyn': 'struct Q { x: i64 }\npub fn size() usize { return #typeof(Q).size }\n'}
    files[owner] = files[owner] + '\n' + declaration + '\n'
    run = check(files)
    name = declaration.removeprefix('pub ').split()[1]
    assert run.returncode != 0 and f'{name} is a builtin type, used by #typeof' in run.stderr, (declaration, run.stderr)

run = check({'main.dyn': 'use "std/io"\n\nstruct P { x: i64, y: i32 }\n\nfn main() {\n  info := #typeof(P)\n'
             '  io.println("{} {} {}", info.size, info.fields.len, info.kind == TypeKind.Struct)\n}\n'})
assert run.returncode == 0 and run.stdout.endswith('16 2 true\n'), run
print('PASS reflection names: TypeInfo/TypeMember/TypeKind reserved in every module; #typeof uses the builtin types')
