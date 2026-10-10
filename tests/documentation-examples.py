#!/usr/bin/env python3
"""Run complete memory documentation programs and check exported contract summaries."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
documents = [ROOT / 'docs/memory-patterns.md', ROOT / 'docs/memory-api-direction.md', ROOT / 'README.md']
# Workspace guides are checked when present; standalone compiler checkouts keep
# their own executable guide and README coverage.
documents += [path for path in (ROOT.parent / 'docs/idiomatic-dyn.md',
                               ROOT.parent / 'docs/collections.md') if path.is_file()]
programs = [(path, source) for path in documents
            for source in re.findall(r'^```dyn\n(.*?)^```', path.read_text(), re.M | re.S)
            if re.search(r'\bfn main\s*\(', source)]
assert sum(path == ROOT / 'docs/memory-patterns.md' for path, _ in programs) == 4
with tempfile.TemporaryDirectory(prefix='dyn-doc-examples-') as temporary:
    for index, (document, source) in enumerate(programs):
        project = Path(temporary) / str(index)
        project.mkdir()
        (project / 'main.dyn').write_text(source)
        for release in (False, True):
            output = project / ('release' if release else 'debug')
            subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet',
                            '--output', str(output), *(['--release'] if release else [])], check=True, timeout=120)
            subprocess.run([str(output)], check=True, timeout=10)
report = json.loads(subprocess.check_output([DYN, 'docs', str(ROOT / 'std/mem'), '--json'], text=True))
declarations = {d['name']: d for f in report['files'] for d in f['declarations']}
assert set(declarations['arena_push']['contracts']) == {
    'ownership', 'invalidation', 'allocation', 'failure', 'thread_safety'}
assert 'no heap fallback' in declarations['arena_push_array']['contracts']['allocation']
print(f'PASS {len(programs)} complete core documentation programs (debug/release) and JSON contract summaries')
