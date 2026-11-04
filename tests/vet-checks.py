#!/usr/bin/env python3
"""dyn vet reports unused locals and imports; --unsafe lists unsafe operations."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
module = str(ROOT / 'tests/vet-checks')
plain = subprocess.run([DYN, 'vet', module], capture_output=True, text=True, timeout=60)
assert plain.returncode == 1 and 'local is never used' in plain.stderr and 'unsafe:' not in plain.stderr, plain
full = subprocess.run([DYN, 'vet', '--unsafe', module], capture_output=True, text=True, timeout=60)
for message in ('unsafe: #slice', 'unsafe: #offset', 'unsafe: pointer cast', 'unsafe: size multiplication'):
    assert message in full.stderr, (message, full.stderr)
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root/'main.dyn').write_text('use "std/mem"\nuse "std/fmt" f\nfn main() {\n  helper()\n}\n')
    (root/'other.dyn').write_text('fn helper() {\n  arena := mem.arena_create(4096)\n  mem.arena_release(arena)\n}\n')
    imports = subprocess.run([DYN, 'vet', str(root)], capture_output=True, text=True, timeout=60)
    assert imports.returncode == 1 and imports.stderr.count('import is never used') == 1, imports
    assert 'main.dyn:2:' in imports.stderr, imports
print('PASS vet: unused locals and the unsafe report')
