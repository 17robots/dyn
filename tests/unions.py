#!/usr/bin/env python3
"""union declarations are gone; the word stays reserved and the error names the replacements."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-unions-') as temporary:
    module = Path(temporary) / 'bad'
    module.mkdir()
    for source in ('union Bits { f: f32, u: u32 }\n', 'pub union Bits { f: f32, u: u32 }\n'):
        (module / 'main.dyn').write_text(source + 'fn main() {}\n')
        checked = subprocess.run([DYN, 'check', str(module)], capture_output=True, text=True, timeout=60)
        assert checked.returncode != 0 and 'union types were removed' in checked.stderr, (source, checked.stderr)
print('PASS unions: declarations rejected with a migration hint')
