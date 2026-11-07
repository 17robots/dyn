#!/usr/bin/env python3
"""Every dyn code block in the docs parses, and complete programs type-check."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
# Historical "before" code and proposals for syntax Dyn does not have.
SKIP = ('docs/migrations/', 'docs/internals/generics-design.md',
        'docs/internals/std-standardization.md',
        'docs/internals/result-shape-std.md')


def parses(directory, source):
    (Path(directory) / 'main.dyn').write_text(source)
    result = subprocess.run([DYN, 'fmt', '--check', directory], capture_output=True, text=True, timeout=30)
    return 'error' not in result.stderr, result.stderr


checked = 0
complete = 0
failures = []
with tempfile.TemporaryDirectory(prefix='dyn-doc-snippets-') as directory:
    for document in sorted((ROOT / 'docs').rglob('*.md')) + [ROOT / 'README.md']:
        relative = document.relative_to(ROOT).as_posix()
        if relative.startswith(SKIP):
            continue
        for match in re.finditer(r'```dyn\n(.*?)```', document.read_text(), re.S):
            block = match.group(1)
            checked += 1
            if re.search(r'^fn main\(\)', block, re.M) and 'use "vendor/' not in block:
                (Path(directory) / 'main.dyn').write_text(block)
                result = subprocess.run([DYN, 'check', directory], capture_output=True, text=True, timeout=30,
                                        env={**os.environ, 'DYN_SDK': str(ROOT)})
                complete += 1
                if result.returncode:
                    failures.append(f'{relative}: {result.stderr.strip().splitlines()[0]}')
            ok, error = parses(directory, block)
            if ok:
                continue
            lines = block.split('\n')
            uses = [line for line in lines if line.startswith('use ')]
            body = [line for line in lines if not line.startswith('use ')]
            ok, error = parses(directory, '\n'.join(uses) + '\nfn main() {\n' + '\n'.join(body) + '\n}\n')
            if not ok:
                failures.append(f'{relative}: {error.strip().splitlines()[0]}')
assert not failures, '\n'.join(failures)
print(f'PASS {checked} documentation snippets parse, {complete} complete programs type-check')
