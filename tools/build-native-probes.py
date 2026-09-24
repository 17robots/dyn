#!/usr/bin/env python3
"""Cross-build an exact, hashed set of probes for execution on native CI runners."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
OUT = ROOT/'build/native-target-probes'
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)

def run(command):
    subprocess.run(list(map(str, command)), cwd=ROOT, check=True, timeout=600)

run([sys.executable, 'tests/readiness-native.py', '--cross'])
run([sys.executable, 'tests/aggregate-abi.py', '--cross'])
run(['zig', 'cc', '-target', 'x86_64-windows-gnu', '-c',
     'tests/process-platform/windows-abi.c', '-o', 'build/windows-process-abi.o'])
manifest = {'schema': 1, 'compiler_sha256': hashlib.sha256(Path(DYN).read_bytes()).hexdigest(), 'targets': {}}
for name, target in [('windows','x86_64-windows'), ('macos','aarch64-macos'), ('aarch64','aarch64-linux')]:
    rows = []
    for mode in ('debug','release'):
        destination = OUT/name/mode
        destination.mkdir(parents=True)
        suffix = '.exe' if name == 'windows' else ''
        for folder, label in [('readiness/native','abi'), ('aggregate-abi','aggregates')]:
            shutil.copy2(ROOT/'build'/folder/(name+'-'+mode+suffix), destination/(label+suffix))
        fixtures = [('arenas','owned-arenas'), ('observe','sdk-observe'), ('memory','sdk-mem')]
        if name != 'aarch64':
            fixtures += [('platform','target-'+name+'-platform'), (name+'-process','process-platform')]
        else:
            shutil.copy2(ROOT/'build/readiness/native'/('aarch64-concurrency-'+mode), destination/'concurrency')
        for label, fixture in fixtures:
            run([DYN,'build',ROOT/'tests'/fixture,'--target',target,'--no-cache','--quiet',
                 '--output',destination/(label+suffix), *(['--release'] if mode == 'release' else [])])
        for artifact in sorted(destination.iterdir()):
            rows.append({'path':str(artifact.relative_to(OUT)), 'mode':mode,
                         'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()})
    manifest['targets'][name] = rows
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
shutil.copy2(ROOT/'tests/run-native-artifacts.py', OUT/'run-native-artifacts.py')
print('Prepared native probes:', {k:len(v) for k,v in manifest['targets'].items()})
