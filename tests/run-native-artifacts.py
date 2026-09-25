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
try:
    if platform.system()!=expected[0] or platform.machine().lower() not in expected[1]:
        raise RuntimeError('Native runner host does not match target')
    manifest=json.loads((root/'manifest.json').read_text())
    if manifest.get('schema')!=1 or not manifest['targets'].get(args.target):
        raise RuntimeError('Missing or unsupported native probe manifest')
    report['compiler_sha256']=manifest['compiler_sha256']
    failures=[]
    for probe in manifest['targets'][args.target]:
        name=probe['path']
        artifact=(root/name).resolve()
        row=dict(artifact=name,mode=probe['mode'],status='failed')
        start=time.monotonic()
        try:
            if not artifact.is_relative_to(root): raise RuntimeError('Artifact escapes download directory')
            digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
            row['sha256']=digest
            if digest!=probe['sha256']: raise RuntimeError('Artifact hash mismatch')
            if platform.system()!='Windows': artifact.chmod(artifact.stat().st_mode|0o111)
            result=subprocess.run([str(artifact)],cwd=artifact.parent,capture_output=True,text=True,errors="replace",timeout=60)
            row.update(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr)
            if result.returncode:
                if platform.system()=='Darwin':
                    trace=subprocess.run(['lldb','--batch','-o','run','-k','bt all','-k','register read',str(artifact)],
                                         cwd=artifact.parent,capture_output=True,text=True,errors='replace',timeout=60)
                    row['debugger']=dict(returncode=trace.returncode,stdout=trace.stdout,stderr=trace.stderr)
                raise RuntimeError(f'exited {result.returncode}')
            row['status']='passed'
        except (OSError,RuntimeError,subprocess.SubprocessError) as error:
            row['error']=str(error);failures.append(name)
        finally:
            row['seconds']=time.monotonic()-start
            report['probes'].append(row)
    if failures: raise RuntimeError('Failed probes: '+', '.join(failures))
    report['status']='passed'
except BaseException as error:
    report.update(status='failed',error=str(error)); raise
finally:
    (root/('native-'+args.target+'.json')).write_text(json.dumps(report,indent=2)+'\n')
print('PASS native '+args.target+' probes')
