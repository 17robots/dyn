#!/usr/bin/env python3
"""Execute downloaded target probes natively, recording artifact hashes and results."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import time
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--target', required=True, choices=['windows','macos','aarch64'])
parser.add_argument('--root', type=Path, default=Path.cwd())
args = parser.parse_args()
root = args.root.resolve()
expected = {'windows':('Windows',('amd64','x86_64')), 'macos':('Darwin',('arm64','aarch64')), 'aarch64':('Linux',('aarch64','arm64'))}[args.target]
report = dict(target=args.target,host=platform.platform(),machine=platform.machine(),status='running',probes=[])
suffix = '.exe' if args.target == 'windows' else ''
paths = [f'{folder}/{args.target}-{mode}{suffix}' for folder in ('readiness/native','aggregate-abi') for mode in ('debug','release')]
if args.target == 'aarch64': paths += ['readiness/native/aarch64-concurrency-'+mode for mode in ('debug','release')]
else: paths += [args.target+'-'+probe+suffix for probe in ('platform','arenas','process')]
try:
    if platform.system()!=expected[0] or platform.machine().lower() not in expected[1]:
        raise RuntimeError('Native runner host does not match target')
    for name in paths:
        artifact=root/name
        if platform.system()!='Windows': artifact.chmod(artifact.stat().st_mode|0o111)
        digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
        start=time.monotonic()
        result=subprocess.run([str(artifact)],cwd=root,capture_output=True,text=True,timeout=60)
        report['probes'].append(dict(artifact=name,sha256=digest,returncode=result.returncode,seconds=time.monotonic()-start,stdout=result.stdout,stderr=result.stderr))
        if result.returncode: raise RuntimeError(f'{name} exited {result.returncode}')
    report['status']='passed'
except BaseException as error:
    report.update(status='failed',error=str(error)); raise
finally:
    (root/('native-'+args.target+'.json')).write_text(json.dumps(report,indent=2)+'\n')
print('PASS native '+args.target+' probes')
