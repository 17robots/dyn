#!/usr/bin/env python3
"""Paired end-to-end compiler qualification on identical generated projects.

Alternates compiler order, disables build caches, compares diagnostics and executed
outputs, and records per-process RSS. No performance threshold or default switch.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
from benchmark import measure

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(folder):
    return {str(p.relative_to(folder)): digest(p) for p in sorted(folder.rglob('*.dyn'))}


def runtime_manifest(executable):
    # Match executable-relative lookup precedence; record available runtime inputs.
    folders = [executable.parent, executable.parent/'../lib/dyn']
    names = {p.name for folder in folders for p in folder.glob('dynrt*.o')}
    records = {}
    for name in sorted(names):
        path = next(folder/name for folder in folders if os.access(folder/name, os.R_OK))
        records[name] = {'path': str(path.resolve()), 'sha256': digest(path)}
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, default=ROOT/'build/dyn-release')
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--lines', type=int, nargs='*', default=[100000, 500000])
    parser.add_argument('--flat', type=int, default=4000)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--modes', choices=('check', 'debug', 'release'), nargs='+', default=['check', 'debug', 'release'])
    parser.add_argument('--output', type=Path, required=True, help='new artifact directory')
    args = parser.parse_args()
    if args.runs < 1 or args.jobs < 1 or args.flat < 0 or any(n < 1 for n in args.lines):
        parser.error('positive runs/jobs/lines and nonnegative flat required')
    if not args.lines and not args.flat:
        parser.error('at least one workload required')
    work = args.output.resolve()
    if work.exists():
        parser.error('--output must be a new directory')
    compilers = {'reference': args.reference.resolve(), 'candidate': args.candidate.resolve()}
    metadata = {}
    for name, executable in compilers.items():
        version = subprocess.run([str(executable), 'version'], check=True, capture_output=True, text=True)
        stamp = Path(str(executable)+'.build.json')
        metadata[name] = {'path': str(executable), 'sha256': digest(executable),
                          'version': version.stdout.strip(),
                          'build_record': json.loads(stamp.read_text()) if stamp.exists() else None,
                          'available_runtime_inputs': runtime_manifest(executable)}
    work.mkdir(parents=True)
    report = {'scope': 'Cold compiler caches, warm OS caches. End-to-end command wall time; '
              'RSS is wait4 per-process maximum, not aggregate simultaneous process-tree memory. '
              'Subphase sums may overlap when jobs exceeds one. Runtime validation excluded from compile timing. Both compilers receive identical sources and flags.',
              'host': platform.platform(), 'machine': platform.machine(),
              'invocation': [sys.executable, *sys.argv], 'compilers': metadata,
              'tools_sha256': {str(p.relative_to(ROOT)): digest(p) for p in
                               (Path(__file__), ROOT/'tools/benchmark.py', ROOT/'tools/generate-scale.py')},
              'std_sha256': manifest(ROOT/'std'), 'runs': args.runs, 'jobs': args.jobs, 'modes': args.modes, 'workloads': []}
    shapes = [(f'lines-{n}', ['--lines', str(n)]) for n in args.lines]
    if args.flat:
        shapes.append((f'flat-{args.flat}', ['--flat', str(args.flat)]))
    for shape, flags in shapes:
        project = work/shape
        generate = [sys.executable, str(ROOT/'tools/generate-scale.py'), *flags, str(project)]
        subprocess.run(generate, check=True, capture_output=True, text=True)
        sources = manifest(project)
        row = {'name': shape, 'generator_command': generate, 'source_sha256': sources,
               'lines': sum(p.read_text().count('\n') for p in project.rglob('*.dyn')),
               'samples': [], 'summary': {}}
        reference_output = None
        diagnostics = {}
        for trial in range(args.runs):
            for mode in (args.modes if trial % 2 == 0 else reversed(args.modes)):
                for name in (('reference','candidate') if trial % 2 == 0 else ('candidate','reference')):
                    output = work/f'{shape}-{name}-{mode}'
                    command = [str(compilers[name]), 'check' if mode == 'check' else 'build', str(project),
                               '--no-cache', '--timings', '--jobs', str(args.jobs)]
                    if mode != 'check':
                        command += ['--'+mode, '--quiet', '--output', str(output)]
                    environment = dict(os.environ, DYN_SDK=str(ROOT), DYN_CACHE_DIR=str(work/f'cache-{shape}-{trial}-{mode}-{name}'))
                    sample = measure(command, environment, 1800)
                    phases = dict((key, float(value)) for key, value in
                                  re.findall(r'^timing (\w+) ([\d.]+) ms$', sample['stderr'], re.M))
                    details = [{'phase': key, 'seconds': float(value)/1000, 'peak_mib': int(peak)}
                               for key, value, peak in re.findall(
                                   r'^timing detail (\w+) ([\d.]+) ms, peak (\d+) MiB$', sample['stderr'], re.M)]
                    diagnostic = re.sub(r'^timing .*\n?', '', sample['stderr'], flags=re.M)
                    signature = (sample['stdout'], diagnostic)
                    if mode in diagnostics:
                        assert signature == diagnostics[mode], (shape, mode, name, 'diagnostic mismatch')
                    else:
                        diagnostics[mode] = signature
                    sample.update(compiler=name, mode=mode, trial=trial, command=command,
                                  environment_overrides={key:environment[key] for key in ('DYN_SDK','DYN_CACHE_DIR')}, phases_ms=phases, detail_samples=details)
                    if mode != 'check':
                        sample['artifact_bytes'] = output.stat().st_size
                        sample['artifact_sha256'] = digest(output)
                        runtime = measure([str(output)], environment, 1800)
                        signature = (runtime['stdout_sha256'], runtime['stderr'])
                        if reference_output is None:
                            reference_output = signature
                        assert signature == reference_output, (shape, mode, name, 'runtime output mismatch')
                        sample['runtime_validation'] = runtime
                    row['samples'].append(sample)
        for mode in args.modes:
            row['summary'][mode] = {}
            for name in compilers:
                values = [s for s in row['samples'] if s['compiler'] == name and s['mode'] == mode]
                peaks = [s['max_rss_bytes'] for s in values if s['max_rss_bytes'] is not None]
                row['summary'][mode][name] = {'median_seconds': statistics.median(s['seconds'] for s in values),
                                             'max_rss_bytes': max(peaks) if peaks else None,
                                             'median_reported_subphase_sum_seconds': {
                                                 phase: statistics.median(sum(d['seconds'] for d in s['detail_samples']
                                                                              if d['phase'] == phase) for s in values)
                                                 for phase in sorted({d['phase'] for s in values for d in s['detail_samples']})}}
        assert report['std_sha256'] == manifest(ROOT/'std'), 'standard library changed during measurements'
        assert sources == manifest(project), 'source changed during measurements'
        report['workloads'].append(row)
        for name, executable in compilers.items():
            assert runtime_manifest(executable) == metadata[name]['available_runtime_inputs'], 'runtime changed during measurements'
            assert digest(executable) == metadata[name]['sha256'], f'{name} compiler changed during measurements'
        (work/'results.json').write_text(json.dumps(report, indent=2)+'\n')
        print(shape, json.dumps(row['summary']), flush=True)
    print(work/'results.json')


if __name__ == '__main__':
    main()
