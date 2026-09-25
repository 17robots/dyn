#!/usr/bin/env python3
"""Create a standalone source release; publishing is a separate action."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import tarfile
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dist', type=Path, default=Path('build/dist'))
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
files = [root/name for name in ('justfile', 'README.md', '.tree-sitter-version', 'grammar.js', 'tree-sitter.json', 'package.json', 'package-lock.json', 'pnpm-lock.yaml', 'binding.gyp', 'CMakeLists.txt', 'Cargo.toml', 'go.mod', 'Package.swift', 'pyproject.toml', 'setup.py') if (root/name).is_file()]
for folder in ('src', 'test', 'queries', 'neovim', 'helix', 'bindings', 'tools'):
    files.extend(p for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.o', '.pyc'))
files = sorted(set(files))
args.dist.mkdir(parents=True, exist_ok=True)
archive = args.dist/'dyn-grammar-candidate.tar.gz'
def normalize(info):
    info.uid = info.gid = 0
    info.mtime = int(os.environ.get('SOURCE_DATE_EPOCH', '0'))
    info.uname = info.gname = ''
    return info
with archive.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
    with tarfile.open(fileobj=compressed, mode='w') as tar:
        for path in files:
            tar.add(path, arcname=str(path.relative_to(root)), filter=normalize)
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
report = dict(status='prepared-not-published', archive_sha256=digest, files={str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
(args.dist/'grammar-publication.json').write_text(json.dumps(report, indent=2)+'\n')
Path(str(archive)+'.sha256').write_text(f'{digest}  {archive.name}\n')
print(f'PASS grammar publication bundle: {archive}')
