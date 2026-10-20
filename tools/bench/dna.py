#!/usr/bin/env python3
"""Compare identical DNA workflows using two compiler-built release binaries.

DNA dependencies must already be built. Runs its existing workflow probe,
including rendering-equivalence checks. Input timings come from the probe;
whole-process wall time includes deliberate waits and is not throughput.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--dyn', type=Path, required=True, help='Compiler used to build the shared probe')
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=3)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error('--samples must be positive')
    args.output.mkdir(parents=True, exist_ok=True)
    project = args.project.resolve()
    binaries = {'baseline': args.baseline.resolve(), 'candidate': args.candidate.resolve()}
    report = {'schema': 1, 'scope': 'Two-round DNA workflow; input latency and resident memory, not compute throughput',
              'binaries': {name: {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                  'bytes': path.stat().st_size} for name, path in binaries.items()}, 'samples': []}
    pattern = re.compile(r'RSS baseline (\d+) KiB, final (\d+) KiB; input mean ([\d.]+) ms, max ([\d.]+) ms')
    env = dict(os.environ, DYN=str(args.dyn.resolve()), DYN_SDK=str(args.sdk.resolve()),
               DNA_PERF_ROUNDS='2', DNA_DEFAULT_SERVERS='0', DNA_DYN_LSP='', DNA_RECOVERY='0',
               XDG_CONFIG_HOME=str(args.output.resolve()/'config'), XDG_STATE_HOME=str(args.output.resolve()/'state'))
    for index in range(args.samples):
        for name in (('baseline', 'candidate') if index % 2 == 0 else ('candidate', 'baseline')):
            result = subprocess.run(['python3', 'tests/workflow_performance.py'], cwd=project,
                                    env=dict(env, DNA_PERF_BINARY=str(binaries[name])),
                                    capture_output=True, text=True, timeout=180)
            log = result.stdout + result.stderr
            (args.output/f'{name}-{index}.log').write_text(log)
            if result.returncode:
                raise SystemExit(f'{name} sample {index} failed; inspect saved log')
            match = pattern.search(log)
            if not match or 'PASS syntax rendering:' not in log:
                raise SystemExit(f'{name}: missing workflow or rendering evidence')
            sample = dict(variant=name, index=index, baseline_RSS_KiB=int(match[1]), final_RSS_KiB=int(match[2]),
                          input_mean_ms=float(match[3]), input_max_ms=float(match[4]))
            report['samples'].append(sample)
            (args.output/'results.json').write_text(json.dumps(report, indent=2)+'\n')
            print(sample, flush=True)
    report['medians'] = {name: {key: statistics.median(s[key] for s in report['samples'] if s['variant'] == name)
                                     for key in ('baseline_RSS_KiB', 'final_RSS_KiB', 'input_mean_ms')}
                         for name in binaries}
    (args.output/'results.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
