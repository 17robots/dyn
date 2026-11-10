#!/usr/bin/env python3
"""Generic structs: layouts, generic functions over them, imports and diagnostics."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
REJECTED = {
    'no arguments': ('struct Box(T) { value: T }\nfn main() {\n  x: Box\n  _ = x\n}\n', 'unknown'),
    'too many': ('struct Box(T) { value: T }\nfn main() {\n  x: Box(i32, u8)\n  _ = x\n}\n', 'unknown'),
    'not generic': ('struct Box { value: i32 }\nfn main() {\n  x: Box(i32)\n  _ = x\n}\n', 'unknown'),
    'by value': ('struct Box(T) { next: Box(T) }\nfn main() {\n  x: Box(i32)\n  _ = x\n}\n', 'itself'),
    'value parameter': ('struct Box(n: i32) { value: i32 }\nfn main() {\n}\n', "parameters are all types"),
}
with tempfile.TemporaryDirectory(prefix='dyn-generic-structs-') as temporary:
    root = Path(temporary)
    for mode in ('--debug', '--release'):
        program = root / ('program' + mode)
        subprocess.run([DYN, 'build', str(ROOT / 'tests/generic-structs'), mode, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=120)
        subprocess.run([str(program)], check=True, timeout=30)
    project = root / 'project'
    (project / 'shapes').mkdir(parents=True)
    (project / 'shapes' / 'shapes.dyn').write_text(
        'pub struct Box(T) { value: T }\n'
        'pub fn wrap(value: $T) Box(T) {\n  result: Box(T)\n  result.value = value\n  return result\n}\n'
        'pub fn read(box: Box($T)) T {\n  return box.value\n}\n')
    (project / 'main.dyn').write_text(
        'use "./shapes" shapes\n'
        'fn twice(box: shapes.Box(i32)) i32 {\n  return box.value * 2\n}\n'
        'fn main() {\n  a := shapes.wrap(4)\n  b: shapes.Box(f64) = .{ value: 1.5 }\n'
        '  if twice(a) != 8 || shapes.read(b) != 1.5 {\n    #panic("imported")\n  }\n}\n')
    program = root / 'imported'
    subprocess.run([DYN, 'build', str(project), '--quiet', '--no-cache', '--output', str(program)], check=True, timeout=120)
    subprocess.run([str(program)], check=True, timeout=30)
    for name, (text, expected) in REJECTED.items():
        directory = root / name.replace(' ', '-')
        directory.mkdir()
        (directory / 'main.dyn').write_text(text)
        result = subprocess.run([DYN, 'check', str(directory)], capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and expected in result.stderr, (name, result.stderr)
    named = root / 'named'
    named.mkdir()
    (named / 'main.dyn').write_text('struct Box(T) { value: T }\nfn main() {\n  x: Box(i32)\n  y: Box(u8) = x\n  _ = y\n}\n')
    result = subprocess.run([DYN, 'check', str(named)], capture_output=True, text=True, timeout=30)
    assert 'Box(u8)' in result.stderr and 'Box(i32)' in result.stderr, result.stderr
print('PASS generic structs, imports and diagnostics')
