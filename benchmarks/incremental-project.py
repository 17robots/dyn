#!/usr/bin/env python3
"""Larger module graph: cold, unchanged, private-body, and public-interface edits."""
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time

DYN = str(Path(os.environ.get('DYN', 'build/dyn')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-incremental-') as directory:
    root = Path(directory)/'app'; root.mkdir()
    cache = Path(directory)/'cache'
    environment = dict(os.environ, DYN_CACHE_DIR=str(cache))
    paths = []
    originals = []
    for index in range(12):
        package = root/f'lib{index}'; package.mkdir()
        source = 'pub fn answer() i32 { return 1 }\n' + ''.join(
            f'pub fn helper{j}(value: i32) i32 {{ return value + {j} }}\n' for j in range(30))
        path = package/'module.dyn'; path.write_text(source)
        paths.append(path); originals.append(source)
    (root/'main.dyn').write_text('\n'.join(f'use "./lib{i}" m{i}' for i in range(12)) +
        '\nfn main() { '+ ' '.join(f'if m{i}.answer() < 1 {{ #panic("bad import") }}' for i in range(12))+' }\n')
    output = Path(directory)/'program'
    def build():
        started = time.monotonic()
        run = subprocess.run([DYN, 'build', str(root), '--jobs', '1', '--quiet', '--verbose', '--output', str(output)],
                             capture_output=True, text=True, env=environment, check=True, timeout=60)
        elapsed = (time.monotonic()-started)*1000
        subprocess.run([str(output)], check=True)
        return {'ms': elapsed, 'cached_modules': run.stderr.count('cached module '),
                'cached_interfaces': run.stderr.count('cached interface ')}
    report = {'compiler_sha256': hashlib.sha256(Path(DYN).read_bytes()).hexdigest(), 'modules': 13, 'jobs': 1, 'samples': {}}
    report['samples']['cold'] = [build()]
    report['samples']['unchanged'] = [build() for _ in range(7)]
    report['samples']['private_body'] = []
    for change in range(7):
        paths[0].write_text(originals[0].replace('return 1 }', f'return {change+2} }}', 1))
        report['samples']['private_body'].append(build())
    report['samples']['public_interface'] = []
    for change in range(7):
        paths[0].write_text(originals[0] + f'pub fn added{change}() i32 {{ return {change} }}\n')
        report['samples']['public_interface'].append(build())
    report['median_ms'] = {name: statistics.median(row['ms'] for row in rows) for name,rows in report['samples'].items()}
    print(json.dumps(report, indent=2))
