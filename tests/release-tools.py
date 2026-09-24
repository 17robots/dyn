#!/usr/bin/env python3
"""Release tooling must fail closed and must not retain stale successful artifacts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='dyn-release-tools-') as directory:
    root=Path(directory)
    (root/'compiler/tools').mkdir(parents=True)
    (root/'docs/release').mkdir(parents=True)
    script=root/'compiler/tools/release-check.py'
    shutil.copy2(ROOT/'compiler/tools/release-check.py',script)
    shutil.copy2(ROOT/'docs/release/toolchain.json',root/'docs/release/toolchain.json')
    (root/'justfile').write_text('all:\n    @exit 90\n')
    output=root/'build/release-check'
    (output/'artifacts').mkdir(parents=True)
    (output/'artifacts/stale.tar.gz').write_bytes(b'old release')
    (output/'RELEASE-NOTES.md').write_text('Old passing result')
    env=dict(os.environ,PATH=str(root/'missing-tools'))
    env.pop('BUILD',None)
    result=subprocess.run([sys.executable,str(script),'--preflight'],env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode != 0, result
    report=json.loads((output/'report.json').read_text())
    assert report['status']=='blocked' and report['preflight']['failures'] and not report['stages'],report
    assert not (output/'artifacts').exists() and not (output/'RELEASE-NOTES.md').exists()
    # Command discovery should work even before dependencies are installed.
    listed=subprocess.run([sys.executable,str(script),'--list'],env=env,capture_output=True,text=True,check=True,timeout=15)
    assert 'quality:' in listed.stdout and 'packages:' in listed.stdout
    invalid=subprocess.run([sys.executable,str(script),'--only','invented-stage'],env=env,capture_output=True,text=True,timeout=15)
    assert invalid.returncode==2, invalid
print('PASS release preflight rejects missing tools, removes stale bundles, validates stage names')
