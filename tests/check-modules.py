#!/usr/bin/env python3
"""Check every shipped SDK module and project; discovery cannot silently omit new modules."""
import json
import os
from pathlib import Path
import subprocess
import sys

compiler = os.environ.get('DYN', './build/dyn')
results = []
for base in ('compiler/std', 'compiler/vendor', 'projects'):
    for folder in sorted({path.parent for path in Path(base).rglob('*.dyn')}):
        target = ('wasm32-wasi' if '/os/wasi' in str(folder) or folder.name == 'wasi-hello' else
                  'wasm32-browser' if folder.name in ('browser-canvas', 'browser-video') else
                  'aarch64-macos' if '/os/macos' in str(folder) else
                  'x86_64-windows' if '/os/windows' in str(folder) else 'x86_64-linux')
        process = subprocess.run([compiler, 'check', str(folder), '--quiet', '--no-cache',
                                  '--target', target], capture_output=True, text=True, timeout=30)
        results.append({'path': str(folder), 'target': target, 'status': process.returncode,
                        'diagnostics': process.stderr})
        if process.returncode:
            print(process.stderr, file=sys.stderr, end='')
Path('build/module-checks.json').write_text(json.dumps(results, indent=2) + '\n')
failed = sum(result['status'] != 0 for result in results)
print(f'{len(results)} SDK/project modules checked; {failed} failed')
sys.exit(bool(failed))
