#!/usr/bin/env python3
"""Cold check/debug/release times on generated programs, as lines per second.

Workloads come from tools/generate-scale.py: multi-module programs at each
--lines size, plus the one-module --flat shape that once made release ThinLTO
take minutes. Every build uses --no-cache. Results go to --output as JSON.

--budget fails when a time falls below a regression floor. The floors sit
well under current numbers so slower machines pass; they catch a pathology,
not small drift. Release time must also grow roughly linearly with size.

Example: python3 tools/scale-benchmark.py --budget
"""
import argparse, json, os, platform, subprocess, sys, tempfile, time
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


def timed(command):
    start = time.monotonic()
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    seconds = time.monotonic() - start
    if result.returncode:
        raise SystemExit(f'failed: {" ".join(command)}\n{result.stderr}')
    return seconds


def measure(dyn, project, work):
    lines = count_lines(project)
    row = {'lines': lines}
    row['check'] = timed([dyn, 'check', str(project)])
    row['debug'] = timed([dyn, 'build', str(project), '--no-cache', '--quiet', '--output', str(work / 'debug')])
    row['release'] = timed([dyn, 'build', str(project), '--release', '--no-cache', '--quiet',
                            '--output', str(work / 'release')])
    for mode in ('check', 'debug', 'release'):
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
    args = parser.parse_args()
    dyn = str(args.dyn.resolve())
    generator = [sys.executable, str(ROOT / 'tools/generate-scale.py')]
    results = {'platform': platform.platform(), 'cpus': os.cpu_count(), 'compiler': dyn,
               'version': subprocess.check_output([dyn, 'version'], text=True).strip(), 'scale': {}}
    with tempfile.TemporaryDirectory(prefix='dyn-scale-') as temporary:
        work = Path(temporary)
        for size in sorted(args.lines):
            project = work / f'scale-{size}'
            subprocess.run([*generator, '--lines', str(size), str(project)], check=True, capture_output=True)
            results['scale'][str(size)] = row = measure(dyn, project, project)
            print(f'{row["lines"]:>8} lines  check {row["check"]:6.2f}s  debug {row["debug"]:6.2f}s  '
                  f'release {row["release"]:6.2f}s', flush=True)
        if args.flat:
            project = work / 'flat'
            subprocess.run([*generator, '--flat', str(args.flat), str(project)], check=True, capture_output=True)
            results['flat'] = row = measure(dyn, project, project)
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
