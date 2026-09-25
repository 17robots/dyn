#!/usr/bin/env python3
"""Reproducible phase/RSS baseline; fresh compiler process per measurement."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import sys
import statistics
import subprocess
import tempfile
import time

# A fresh helper makes RUSAGE_CHILDREN specific to this invocation, avoiding
# the cumulative high-water mark of a long-lived benchmark runner.
if len(sys.argv) > 1 and sys.argv[1] == '--measure':
    start = time.monotonic()
    run = subprocess.run(sys.argv[2:], capture_output=True, text=True, timeout=180)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    rss = usage.ru_maxrss / 1024 if sys.platform == 'darwin' else usage.ru_maxrss
    print(json.dumps({'returncode': run.returncode, 'stderr': run.stderr,
                     'wall_ms': (time.monotonic()-start)*1000, 'peak_rss_kib': rss}))
    sys.exit(0)

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repeats', type=int, default=3)
parser.add_argument('--output', type=Path)
args = parser.parse_args()
if args.repeats < 1:
    parser.error('--repeats must be positive')
dyn = str(Path(os.environ.get('DYN', ROOT/'build/dyn')).resolve())
report = {'compiler': subprocess.check_output([dyn, 'version'], text=True).strip(),
          'compiler_sha256': hashlib.sha256(Path(dyn).read_bytes()).hexdigest(),
          'host': platform.platform(), 'jobs': 1, 'cache': False, 'repeats': args.repeats,
          'rss_scope': 'fresh helper RUSAGE_CHILDREN maximum RSS in KiB; includes waited-for compiler children',
          'detail_scope': 'sum per-invocation durations; nested inside load/check/codegen, not additive to them',
          'workloads': []}
with tempfile.TemporaryDirectory(prefix='dyn-phases-') as directory:
    temp = Path(directory)
    workloads = []
    for modules, functions in [(4, 25), (20, 50)]:
        root = temp/f'modules-{modules}-functions-{functions}'; root.mkdir()
        imports = []
        calls = []
        for index in range(modules):
            package = root/f'lib{index}'; package.mkdir()
            (package/'module.dyn').write_text(''.join(
                f'pub fn f{j}(value: i64) i64 {{ return value + {j} }}\n' for j in range(functions)))
            imports.append(f'use "./lib{index}" m{index}')
            calls.append(f'_ = m{index}.f0({index})')
        (root/'main.dyn').write_text('\n'.join(imports)+'\nfn main() { '+' '.join(calls)+' }\n')
        workloads.append((root.name, root))
    workloads.append(('sdk-unicode', ROOT/'tests/sdk-unicode-text'))
    for name, root in workloads:
        for mode in ('check', 'debug', 'release'):
            samples = []
            for iteration in range(args.repeats):
                command = [dyn, 'check' if mode == 'check' else 'build', str(root), '--quiet', '--no-cache', '--timings', '--jobs', '1']
                if mode != 'check': command += ['--no-link', '--output', str(temp/'module.o')]
                if mode == 'release': command += ['--release']
                measured = json.loads(subprocess.check_output([sys.executable, __file__, '--measure', *command], text=True, timeout=190))
                if measured['returncode']: raise RuntimeError(measured['stderr'])
                phases = {}
                for detail, phase, duration in re.findall(r'^timing (detail )?(\w+) ([\d.]+) ms$', measured['stderr'], re.M):
                    key = ('detail_' if detail else '') + phase
                    phases[key] = phases.get(key, 0) + float(duration)
                assert 'load' in phases and 'detail_sema' in phases, measured['stderr']
                samples.append({'wall_ms': measured['wall_ms'], 'peak_rss_kib': measured['peak_rss_kib'], 'phases_ms': phases})
            row = {'name': name, 'mode': mode, 'samples': samples,
                   'median_wall_ms': statistics.median(s['wall_ms'] for s in samples),
                   'median_peak_rss_kib': statistics.median(s['peak_rss_kib'] for s in samples),
                   'median_phases_ms': {key: statistics.median(s['phases_ms'].get(key, 0) for s in samples) for key in samples[0]['phases_ms']}}
            report['workloads'].append(row)
text = json.dumps(report, indent=2)+'\n'
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(text)
else: print(text, end='')
