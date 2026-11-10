#!/usr/bin/env python3
"""Generic enums: construction, case, inference, imports and diagnostics."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SLOT = 'enum Slot(T) { Empty, Full: T }\n'
REJECTED = {
    'no arguments': (SLOT + 'fn main() {\n  x: Slot\n  _ = x\n}\n', 'unknown'),
    'too many': (SLOT + 'fn main() {\n  x: Slot(i32, u8)\n  _ = x\n}\n', 'unknown'),
    'not generic': ('enum Plain { A, B }\nfn main() {\n  x: Plain(i32)\n  _ = x\n}\n', 'unknown'),
    'bare variant': (SLOT + 'fn main() {\n  x := Slot.Full(1)\n  _ = x\n}\n', 'type arguments'),
    'unknown argument': (SLOT + 'fn main() {\n  x := Slot(Nope).Full(1)\n  _ = x\n}\n', 'error'),
    'by value': ('enum Slot(T) { Empty, Next: Slot(T) }\nfn main() {\n  x: Slot(i32)\n  _ = x\n}\n', 'itself'),
    'first payload': ('enum Slot(T) { Full: T, Empty }\nfn main() {\n}\n', 'first enum variant'),
    'wrong payload': (SLOT + 'fn main() {\n  x := Slot(i32).Full(true)\n  _ = x\n}\n', 'mismatch'),
    'not exhaustive': (SLOT + 'fn main() {\n  x: Slot(i32)\n  case x {\n    Slot(i32).Empty => { }\n  }\n}\n', 'exhaustive'),
    'other instance': (SLOT + 'fn main() {\n  x: Slot(i32)\n  y: Slot(u8) = x\n  _ = y\n}\n', 'mismatch'),
    'type carried by argument': ('struct Box(T) { value: T }\nfn f(T: type, b: Box(T)) { }\n'
                                 'fn main() {\n  a: Box(i32)\n  f(i32, a)\n}\n', 'T is in the type of `b`, so it is inferred'),
}
with tempfile.TemporaryDirectory(prefix='dyn-generic-enums-') as temporary:
    root = Path(temporary)
    for mode in ('--debug', '--release'):
        program = root / ('program' + mode)
        subprocess.run([DYN, 'build', str(ROOT / 'tests/generic-enums'), mode, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=120)
        subprocess.run([str(program)], check=True, timeout=30)
    project = root / 'project'
    (project / 'shapes').mkdir(parents=True)
    (project / 'shapes' / 'shapes.dyn').write_text(
        'pub enum Slot(T) { Empty, Full: T }\n'
        'pub fn get(slot: Slot($T), fallback: $T) T {\n  case slot {\n    Slot(T).Empty => {\n      return fallback\n    }\n'
        '    Slot(T).Full value => {\n      return value\n    }\n  }\n}\n')
    (project / 'main.dyn').write_text(
        'use "./shapes" shapes\n'
        'fn main() {\n  a := shapes.Slot(i32).Full(4)\n  case a {\n    shapes.Slot(i32).Empty => {\n      #panic("empty")\n    }\n'
        '    shapes.Slot(i32).Full value => {\n      if value != 4 {\n        #panic("value")\n      }\n    }\n  }\n'
        '  if shapes.get(a, 0) != 4 {\n    #panic("imported")\n  }\n}\n')
    program = root / 'imported'
    subprocess.run([DYN, 'build', str(project), '--quiet', '--no-cache', '--output', str(program)], check=True, timeout=120)
    subprocess.run([str(program)], check=True, timeout=30)
    for name, (text, expected) in REJECTED.items():
        directory = root / name.replace(' ', '-')
        directory.mkdir()
        (directory / 'main.dyn').write_text(text)
        result = subprocess.run([DYN, 'check', str(directory)], capture_output=True, text=True, timeout=30)
        assert result.returncode != 0, name
        assert expected in result.stdout + result.stderr, (name, result.stdout, result.stderr)
print('PASS generic enums, imports and diagnostics')
