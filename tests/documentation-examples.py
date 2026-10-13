#!/usr/bin/env python3
"""Run every complete documentation program and check exported contract summaries."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
# Every complete program in the docs and README must build and run. Migration
# guides show old code on purpose.
documents = sorted(path for path in (ROOT / 'docs').rglob('*.md') if 'migrations' not in path.parts)
documents.append(ROOT / 'README.md')
programs = [(path, source) for path in documents
            for source in re.findall(r'^```dyn\n(.*?)^```', path.read_text(), re.M | re.S)
            if re.search(r'\bfn main\s*\(', source)
            # Raw vendor bindings are generated per machine by `just vendor-bindings`.
            and not re.search(r'^use "vendor/[^"]*/raw"', source, re.M)]
assert sum(path == ROOT / 'docs/guide/memory-patterns.md' for path, _ in programs) == 5
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
print(f'PASS {len(programs)} complete documentation programs (debug/release) and JSON contract summaries')
