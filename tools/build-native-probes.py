#!/usr/bin/env python3
"""Cross-build an exact, hashed set of probes for execution on native CI runners."""
import ast
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
        # macOS debug builds keep <output>.dynnative.o for the debugger; it is not a probe.
        for kept in destination.glob('*.dynnative.o'): kept.unlink()
        for artifact in sorted(destination.iterdir()):
            rows.append({'path':str(artifact.relative_to(OUT)), 'mode':mode,
                         'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()})
    manifest['targets'][name] = rows
# New ports run the same thread/atomic/remainder and panic-cleanup contracts.
contracts = {}
for node in ast.parse((ROOT/'tests/cross-runtime.py').read_text()).body:
    if isinstance(node, ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('SOURCE','PANIC'):
        contracts[node.targets[0].id] = ast.literal_eval(node.value)
for name,target in [('windows-arm64','aarch64-windows'),('macos-x64','x86_64-macos')]:
    rows=[]
    for mode in ('debug','release'):
        destination=OUT/name/mode;destination.mkdir(parents=True)
        for label,key in [('runtime','SOURCE'),('panic','PANIC')]:
            project=OUT/'sources'/name/mode/label;project.mkdir(parents=True)
            (project/'main.dyn').write_text(contracts[key])
            output=destination/(label+('.exe' if 'windows' in name else ''))
            run([DYN,'build',project,'--target',target,'--no-cache','--quiet','--'+mode,'--output',output])
            rows.append(dict(path=str(output.relative_to(OUT)),mode=mode,sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                             expected_returncode=101 if key=='PANIC' else 0,
                             expected_stdout='inner cleanup\nouter cleanup\n' if key=='PANIC' else 'cross runtime ready\n'))
        project=OUT/'sources'/name/mode/'shared';project.mkdir(parents=True)
        (project/'main.dyn').write_text('pub fn calculate(value:f64) f64 { return value % 2.0 }\n')
        output=destination/('shared.dll' if 'windows' in name else 'shared.dylib')
        run([DYN,'build',project,'--target',target,'--no-cache','--quiet','--'+mode,'--shared','--output',output])
        rows.append(dict(path=str(output.relative_to(OUT)),mode=mode,kind='shared',
                         sha256=hashlib.sha256(output.read_bytes()).hexdigest()))
    manifest['targets'][name]=rows
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
shutil.copy2(ROOT/'tests/run-native-artifacts.py', OUT/'run-native-artifacts.py')
# Debug builds use native emission: stage the differential corpus against x86-64 Linux too.
differential = ROOT/'tools/backend/native-differential.py'
for name, target in [('windows','x86_64-windows'), ('macos','aarch64-macos'), ('aarch64','aarch64-linux'), ('windows-arm64','aarch64-windows'), ('macos-x64','x86_64-macos')]:
    run([sys.executable, differential, '--target', target, '--compiler', DYN, '--stage', OUT/'differential'/name])
shutil.copy2(differential, OUT/'native-differential.py')
print('Prepared native probes:', {k:len(v) for k,v in manifest['targets'].items()})
