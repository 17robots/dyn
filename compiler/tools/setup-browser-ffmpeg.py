#!/usr/bin/env python3
"""Stage the pinned single-thread FFmpeg Wasm core without global installation."""
import argparse, base64, hashlib, io, json, shutil, tarfile, urllib.request
from pathlib import Path
VERSION = '0.12.10'
INTEGRITY = 'dzNplnn2Nxle2c2i2rrDhqcB19q9cglCkWnoMTDN9Q9l3PvdjZWd1HfSPjCNWc/p8Q3CT+Es9fWOR0UhAeYQZA=='
URL = f'https://registry.npmjs.org/@ffmpeg/core/-/core-{VERSION}.tgz'
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, default=Path('build/browser-ffmpeg'))
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
archive = a.output/'core.tgz'
data = archive.read_bytes() if archive.is_file() else urllib.request.urlopen(URL, timeout=120).read()
if base64.b64encode(hashlib.sha512(data).digest()).decode() != INTEGRITY:
    raise SystemExit('FFmpeg core integrity mismatch; remove the invalid cached core.tgz and retry')
archive.write_bytes(data)
with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
    for name in ('dist/umd/ffmpeg-core.js', 'dist/umd/ffmpeg-core.wasm', 'package.json'):
        source = tar.extractfile('package/'+name)
        if source is None: raise RuntimeError('Missing '+name)
        (a.output/Path(name).name).write_bytes(source.read())
(a.output/'provenance.json').write_text(json.dumps(dict(package='@ffmpeg/core', version=VERSION, url=URL, integrity='sha512-'+INTEGRITY),indent=2)+'\n')
location = Path(__file__).resolve().parents[1]
vendor = location/'vendor' if (location/'vendor').is_dir() else location/'share/dyn/vendor'
for name in ('pipeline.mjs', 'worker.js'):
    shutil.copy2(vendor/'ffmpeg/browser'/name, a.output/name)
print('Staged @ffmpeg/core '+VERSION+' in '+str(a.output))
