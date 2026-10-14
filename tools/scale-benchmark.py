#!/usr/bin/env python3
"""Cold check/debug/release times on generated programs, as lines per second.

Workloads come from tools/generate-scale.py: multi-module programs at each
--lines size, plus the one-module --flat shape that once made release ThinLTO
take minutes. Every build uses --no-cache. Results go to --output as JSON.
Results include source/tool hashes and per-command peak RSS on Linux using GNU
time or the repository's compiled peak helper. RSS is not the simultaneous total
of a process tree.
Repeated runs alternate mode order; existing time keys contain medians.

--budget fails when a time falls below a regression floor. The floors sit
well under current numbers so slower machines pass; they catch a pathology,
not small drift. Release time must also grow roughly linearly with size.

Example: python3 tools/scale-benchmark.py --budget
"""
import argparse, hashlib, json, os, platform, shlex, statistics, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Minimum lines per second. Targets are separate: check above 1M, debug above 200k.
FLOORS = {'check': 100_000, 'debug': 60_000, 'release': 20_000}
FLAT_RELEASE_SECONDS = 30
# Release seconds per line at the largest size may be at most this many times
# the smallest size's, so doubling the program cannot quadruple the build.
LINEAR_SLACK = 2.0


def count_lines(directory):
    return sum(path.read_text().count('\n') for path in directory.rglob('*.dyn'))


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def rss_tool():
    unavailable = {'status': 'unavailable', 'tool': None, 'kind': None,
                   'reason': 'RSS measurement requires Linux'}
    if sys.platform != 'linux':
        return unavailable
    candidate = Path('/usr/bin/time')
    if os.access(candidate, os.X_OK):
        try:
            probe = subprocess.run([str(candidate), '--version'], capture_output=True, text=True, timeout=10)
            if probe.returncode == 0 and 'gnu' in probe.stdout.lower():
                return {'status': 'available', 'tool': str(candidate), 'kind': 'gnu-time',
                        'tool_sha256': sha256(candidate), 'precision_kib': 1,
                        'scope': 'GNU time per-command maximum resident set size; not simultaneous process-tree memory'}
        except (OSError, subprocess.TimeoutExpired):
            pass
    source = ROOT / 'tools/compare/peak.c'
    build = Path(os.environ.get('BUILD', ROOT / 'build')).resolve()
    helper = build / 'scale-peak'
    command = [*shlex.split(os.environ.get('CC', 'cc')), '-O2', str(source), '-o', str(helper)]
    try:
        build.mkdir(parents=True, exist_ok=True)
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
        return {'status': 'available', 'tool': str(helper), 'kind': 'peak-helper',
                'tool_sha256': sha256(helper), 'source': str(source),
                'source_sha256': sha256(source), 'build_command': command,
                'precision_kib': 102.4,
                'scope': 'Linux RUSAGE_CHILDREN maximum individual-process RSS, including reaped descendants; not simultaneous process-tree memory'}
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        unavailable['reason'] = f'GNU time unavailable; peak helper build failed: {error}'
        return unavailable


def timed(command, memory_tool):
    peak_rss = None
    with tempfile.TemporaryDirectory(prefix='dyn-scale-rss-') as temporary:
        report = Path(temporary) / 'rss'
        kind = memory_tool['kind']
        measured = command
        if kind == 'gnu-time':
            measured = [memory_tool['tool'], '-f', '%M', '-o', str(report), *command]
        elif kind == 'peak-helper':
            measured = [memory_tool['tool'], *command]
        start = time.monotonic()
        result = subprocess.run(measured, capture_output=True, text=True, timeout=1800)
        seconds = time.monotonic() - start
        if kind == 'gnu-time' and result.returncode == 0:
            peak_rss = int(report.read_text().strip())
        elif kind == 'peak-helper' and result.returncode == 0:
            # The helper appends one JSON record after the command's stderr.
            # Its RSS is rounded to 0.1 MiB; retain that precision in metadata.
            try:
                # Command diagnostics need not end with a newline.
                record_start = result.stderr.rfind('{"seconds":')
                measurement = json.loads(result.stderr[record_start:])
                peak_rss = round(measurement['rss_mib'] * 1024, 1)
                seconds = measurement['seconds']
                if peak_rss < 0 or seconds <= 0:
                    raise ValueError('invalid RSS or elapsed time')
            except (ValueError, KeyError, IndexError, TypeError) as error:
                raise SystemExit(f'invalid peak helper report: {error}\n{result.stderr}') from error
    if result.returncode:
        raise SystemExit(f'failed: {" ".join(command)}\n{result.stderr}')
    return {'seconds': seconds, 'peak_rss_kib': peak_rss}


def measure(dyn, project, work, repetitions, memory_tool):
    lines = count_lines(project)
    sources = {path.relative_to(project).as_posix(): sha256(path)
               for path in sorted(project.rglob('*.dyn'))}
    row = {'lines': lines, 'source_sha256': sources,
           'corpus_sha256': hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()}
    commands = {
        'check': [dyn, 'check', str(project)],
        'debug': [dyn, 'build', str(project), '--no-cache', '--quiet', '--output', str(work / 'debug')],
        'release': [dyn, 'build', str(project), '--release', '--no-cache', '--quiet',
                    '--output', str(work / 'release')],
    }
    row['commands'] = commands
    row['samples'] = {mode: [] for mode in commands}
    row['mode_order'] = []
    for repetition in range(repetitions):
        order = list(commands) if repetition % 2 == 0 else list(reversed(commands))
        row['mode_order'].append(order)
        for mode in order:
            row['samples'][mode].append(timed(commands[mode], memory_tool))
    for mode in commands:
        row[mode] = statistics.median(sample['seconds'] for sample in row['samples'][mode])
        peaks = [sample['peak_rss_kib'] for sample in row['samples'][mode]
                 if sample['peak_rss_kib'] is not None]
        row[mode + '_peak_rss_kib'] = max(peaks) if peaks else None
        row[mode + '_lines_per_second'] = round(lines / row[mode])
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    default = ROOT / 'build' / ('dyn-release.exe' if os.name == 'nt' else 'dyn-release')
    parser.add_argument('--dyn', type=Path, default=default)
    parser.add_argument('--lines', type=int, nargs='*', default=[100_000, 500_000],
                        help='multi-module sizes; give none to run only the one-module workload')
    parser.add_argument('--flat', type=int, default=4000, help='functions in the one-module workload; 0 skips it')
    parser.add_argument('--output', type=Path, default=ROOT / 'build' / 'scale-benchmark.json')
    parser.add_argument('--budget', action='store_true', help='fail when a regression floor is missed')
    parser.add_argument('--repetitions', type=int, default=1,
                        help='cold runs per mode; alternate mode order and report median times')
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error('--repetitions must be at least 1')
    dyn = str(args.dyn.resolve())
    generator = [sys.executable, str(ROOT / 'tools/generate-scale.py')]
    memory_tool = rss_tool()
    results = {'platform': platform.platform(), 'cpus': os.cpu_count(), 'compiler': dyn,
               'version': subprocess.check_output([dyn, 'version'], text=True).strip(), 'scale': {},
               'compiler_sha256': sha256(Path(dyn)),
               'generator_sha256': sha256(Path(generator[1])),
               'benchmark_sha256': sha256(Path(__file__)),
               'host': {'machine': platform.machine(), 'processor': platform.processor(),
                        'python': platform.python_version()},
               'repetitions': args.repetitions, 'time_summary': 'median',
               'peak_rss': {**memory_tool, 'unit': 'KiB', 'summary': 'maximum across samples'},
               'invocation': [sys.executable, *sys.argv]}
    with tempfile.TemporaryDirectory(prefix='dyn-scale-') as temporary:
        work = Path(temporary)
        for size in sorted(args.lines):
            project = work / f'scale-{size}'
            command = [*generator, '--lines', str(size), str(project)]
            subprocess.run(command, check=True, capture_output=True)
            results['scale'][str(size)] = row = measure(dyn, project, project, args.repetitions, memory_tool)
            row['generator_command'] = command
            print(f'{row["lines"]:>8} lines  check {row["check"]:6.2f}s  debug {row["debug"]:6.2f}s  '
                  f'release {row["release"]:6.2f}s', flush=True)
        if args.flat:
            project = work / 'flat'
            command = [*generator, '--flat', str(args.flat), str(project)]
            subprocess.run(command, check=True, capture_output=True)
            results['flat'] = row = measure(dyn, project, project, args.repetitions, memory_tool)
            row['generator_command'] = command
            print(f'{row["lines"]:>8} lines  check {row["check"]:6.2f}s  debug {row["debug"]:6.2f}s  '
                  f'release {row["release"]:6.2f}s  (one module)', flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + '\n')
    if not args.budget:
        return
    failures = []
    for size, row in results['scale'].items():
        for mode, floor in FLOORS.items():
            if row[mode + '_lines_per_second'] < floor:
                failures.append(f'{size} lines: {mode} {row[mode + "_lines_per_second"]} lines/s < {floor}')
    rows = [results['scale'][str(size)] for size in sorted(args.lines)]
    if len(rows) > 1:
        small, large = rows[0], rows[-1]
        growth = (large['release'] / large['lines']) / (small['release'] / small['lines'])
        if growth > LINEAR_SLACK:
            failures.append(f'release time per line grew {growth:.2f}x from {small["lines"]} to {large["lines"]} lines')
    if 'flat' in results and results['flat']['release'] > FLAT_RELEASE_SECONDS:
        failures.append(f'one-module release took {results["flat"]["release"]:.1f}s > {FLAT_RELEASE_SECONDS}s')
    if failures:
        raise SystemExit('budget missed:\n  ' + '\n  '.join(failures))
    print('PASS compile-speed budget')


if __name__ == '__main__':
    main()
