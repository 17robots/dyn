#!/usr/bin/env python3
"""distinct, packed and is are reserved everywhere, and still work as keywords."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-contextual-keywords-') as temporary:
    root = Path(temporary)
    for release in (False, True):
        program = root / f'program-{release}'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/contextual-keywords'), '--quiet', '--no-cache',
                        '--output', str(program)] + (['--release'] if release else []), check=True, timeout=120)
        result = subprocess.run([str(program)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0 and result.stdout == 'ok\n', result
    for word in ('distinct', 'packed', 'union'):
        for source in (f'fn main() {{\n  {word} := 1\n  _ = {word}\n}}\n', f'struct S {{ {word}: i32 }}\nfn main() {{}}\n',
                       f'fn {word}() {{}}\nfn main() {{}}\n'):
            module = root / 'bad'
            module.mkdir(exist_ok=True)
            (module / 'main.dyn').write_text(source)
            checked = subprocess.run([DYN, 'check', str(module)], capture_output=True, text=True, timeout=60)
            assert checked.returncode != 0 and 'reserved keyword' in checked.stderr, (word, source, checked.stderr)
print('PASS reserved keywords: distinct, packed and union reject names and work as keywords (debug/release)')
