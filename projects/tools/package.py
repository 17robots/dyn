#!/usr/bin/env python3
"""Package example sources with their standalone justfile and validation tools."""
import argparse
import gzip
import hashlib
import os
from pathlib import Path
import tarfile
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dist', type=Path, default=Path('build/dist'))
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
files = [root/name for name in ('justfile', 'README.md', 'validate.sh')]
for folder in root.iterdir():
    if folder.is_dir() and (folder.name == 'tools' or (folder/'main.dyn').is_file()):
        files.extend(p for p in folder.rglob('*') if p.is_file() and not any(x.startswith('.') or x in ('build', '__pycache__') for x in p.relative_to(root).parts) and p.suffix not in ('.pyc', '.o', '.wasm') and '.dyncache' not in p.name)
args.dist.mkdir(parents=True, exist_ok=True)
archive = args.dist/'dyn-projects-candidate.tar.gz'
def normalize(info):
    info.uid = info.gid = 0
    info.mtime = int(os.environ.get('SOURCE_DATE_EPOCH', '0'))
    info.uname = info.gname = ''
    return info
with archive.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
    with tarfile.open(fileobj=compressed, mode='w') as tar:
        for path in sorted(files):
            tar.add(path, arcname=str(path.relative_to(root)), filter=normalize)
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
Path(str(archive)+'.sha256').write_text(f'{digest}  {archive.name}\n')
print(f'PASS projects source bundle: {archive}')
