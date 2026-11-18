#!/usr/bin/env python3
"""Every pass DYN_SKIP can name is optional: skipping it, or all of them,
leaves real programs' output unchanged. tools/bisect-passes.py relies on it."""
import concurrent.futures
import os
from pathlib import Path
import runpy
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
PASSES = runpy.run_path(str(ROOT / 'tools/bisect-passes.py'), run_name='passes')['PASSES']
PROJECTS = [ROOT / 'tests/codegen-kernels/sha256', ROOT / 'tests/codegen-kernels/deflate', ROOT / 'tests/kernels/structs',
            ROOT / 'tests/peer-widening', ROOT / 'tests/vector-loops']


def run(project, skip, work):
    program = work / f'{project.name}-{skip.replace(",", "-") or "none"}'
    subprocess.run([DYN, 'build', str(project), '--release', '--quiet', '--no-cache', '--output', str(program)],
                   check=True, timeout=600, env={**os.environ, 'DYN_SKIP': skip})
    result = subprocess.run([str(program)], cwd=project, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
    return result.returncode, result.stdout


with tempfile.TemporaryDirectory(prefix='dyn-optional-passes-') as temporary:
    work = Path(temporary)
    cases = [(project, skip) for project in PROJECTS for skip in ['', *PASSES, ','.join(PASSES)]]
    with concurrent.futures.ThreadPoolExecutor(max(1, min(16, os.cpu_count() or 1))) as pool:
        results = dict(zip(cases, pool.map(lambda case: run(case[0], case[1], work), cases)))
    for project, skip in cases:
        assert results[(project, skip)] == results[(project, '')], (project.name, skip)
print(f'PASS optional passes: {len(PASSES)} passes, alone and all together, keep {len(PROJECTS)} programs\' output')
