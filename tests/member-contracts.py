#!/usr/bin/env python3
"""Indexed type/member lookup must preserve owners, offsets and runtime values."""
import os, subprocess, tempfile
from pathlib import Path
DYN = str(Path(os.environ.get('DYN', 'build/dyn')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-members-') as directory:
    root = Path(directory)
    text = ''.join(f'struct T{i} {{ value: i32 }}\ntype A{i} = T{i}\n' for i in range(80))
    fields = ', '.join(f'f{i}: i32' for i in range(80))
    values = ', '.join(f'f{i}: {i}' for i in range(80))
    text += f'struct Wide {{ {fields} }}\nstruct Other {{ {fields} }}\n'
    text += 'enum Choice { '+', '.join(f'V{i}' for i in range(80))+' }\n'
    text += 'fn read(x: A79) i32 { return x.value }\n'
    text += f'fn main() {{ x := Wide{{ {values} }} y := Other{{ {values} }} '
    text += 'if read(T79{value: 31}) != 31 || x.f79 != 79 || x.f32 != 32 || y.f79 != 79 || Choice.V79 == Choice.V0 { #panic("member index") } }\n'
    for module in ('left', 'right'):
        package = root/module; package.mkdir()
        (package/'module.dyn').write_text(''.join(f'struct Private{i} {{ x: i32 }}\n' for i in range(40))+'pub fn value() i32 { x := Private39{x: 7} return x.x }\n')
    text = 'use "./left" l\nuse "./right" r\n'+text.replace('if read(', 'if l.value() != 7 || r.value() != 7 || read(')
    source = root/'main.dyn'; source.write_text(text); output = root/'program'
    for flags in ([], ['--release']):
        subprocess.run([DYN, 'build', str(root), '--no-cache', '--quiet', '--output', str(output), *flags], check=True)
        subprocess.run([str(output)], check=True)
    source.write_text(text.replace('x.f79 !=', 'x.missing !='))
    run = subprocess.run([DYN, 'check', str(root), '--no-cache', '--quiet'], capture_output=True, text=True)
    assert run.returncode and 'field' in run.stderr, run.stderr
print('PASS indexed types, aliases, wide members, variants and module ownership')
