#!/usr/bin/env python3
"""Hash native objects for a fixed project corpus.

Refactors of the emitter that must not change x86-64 output compare the
printed manifest before and after (`--output` writes it, `--compare` checks).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT.parent

def corpus():
    roots = [ROOT/'tests', ROOT/'std', WORKSPACE/'projects']
    found = []
    for root in roots:
        if root.exists():
            found += sorted(p.parent for p in root.rglob('main.dyn'))
    return found

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT/'build/dyn')
    parser.add_argument('--target', default='x86_64-linux')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    hashes = {}
    with tempfile.TemporaryDirectory(prefix='dyn-object-hashes-') as directory:
        for index, project in enumerate(corpus()):
            for flags in ([], ['--debug-info']):
                output = Path(directory)/f'{index}'
                result = subprocess.run([str(args.compiler), 'build', str(project), '--backend', 'native',
                                         '--target', args.target, '--no-link', '--no-cache', '--quiet',
                                         '--output', str(output), *flags],
                                        capture_output=True, timeout=300)
                key = f'{project.relative_to(WORKSPACE)} {" ".join(flags)}'.strip()
                obj = Path(str(output)+'.o')
                hashes[key] = hashlib.sha256(obj.read_bytes()).hexdigest() if result.returncode == 0 and obj.exists() else f'exit {result.returncode}'
                obj.unlink(missing_ok=True)
    if args.output:
        args.output.write_text(json.dumps(hashes, indent=1, sort_keys=True))
    built = sum(not v.startswith('exit') for v in hashes.values())
    if args.compare:
        before = json.loads(args.compare.read_text())
        changed = [k for k in sorted(set(before) | set(hashes)) if before.get(k) != hashes.get(k)]
        for key in changed:
            print(f'CHANGED {key}: {before.get(key)} -> {hashes.get(key)}')
        if changed:
            raise SystemExit(f'{len(changed)} of {len(hashes)} objects changed')
        print(f'PASS {len(hashes)} objects identical ({built} built)')
    else:
        print(f'{len(hashes)} objects ({built} built)')

if __name__ == '__main__':
    main()
