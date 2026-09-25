#!/usr/bin/env python3
"""Clean release builds must agree across caches, output names, cwd and worker counts."""
import hashlib, json, os, subprocess, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve()
rows = []
with tempfile.TemporaryDirectory(prefix='dyn-repro-') as directory:
    work = Path(directory)
    for fixture in ('tests/multi-file', 'projects/multi-module', 'tests/owned-arenas', 'tests/sdk-unicode-text'):
        samples = []
        for run, jobs in enumerate((1, 2, 0)):
            cache = work/f'cache-{len(rows)}-{run}'; cache.mkdir()
            output = work/f'output-{len(rows)}-{run}'
            command = [str(DYN), 'build', str(ROOT/fixture), '--release', '--no-cache', '--quiet', '--output', str(output)]
            if jobs: command += ['--jobs', str(jobs)]
            result = subprocess.run(command, cwd=ROOT if run == 0 else work,
                env=dict(os.environ, DYN_CACHE_DIR=str(cache)), capture_output=True, text=True, timeout=180)
            assert result.returncode == 0, result.stderr
            assert not list(cache.iterdir()), "--no-cache wrote cache artifacts"
            subprocess.run([str(output)], check=True, capture_output=True, timeout=30)
            samples.append(hashlib.sha256(output.read_bytes()).hexdigest())
        assert len(set(samples)) == 1, (fixture, samples)
        rows.append(dict(fixture=fixture, sha256=samples[0], jobs=[1,2,0]))
report = dict(compiler_sha256=hashlib.sha256(DYN.read_bytes()).hexdigest(),
    contract='same absolute source/SDK paths and toolchain; clean caches, output names, cwd and worker counts vary', builds=rows)
(ROOT/'build/readiness').mkdir(parents=True, exist_ok=True)
(ROOT/'build/readiness/reproducibility.json').write_text(json.dumps(report, indent=2)+'\n')
print('PASS 12 uncached release builds: deterministic bytes and runtime results')
