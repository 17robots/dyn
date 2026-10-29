#!/usr/bin/env python3
"""Compare compile time of two or more compilers on the same projects.

Runs each compiler on each project in shuffled, interleaved order so drift on
a busy host affects all of them alike. Reports median wall time, median CPU
time (user + system) and peak RSS. With --compare-output, also checks that
every compiler writes byte-identical objects. Compiler caches are disabled;
OS caches stay warm.

Example:
  python3 tools/bench/compile.py --compiler old=/tmp/dyn-old --compiler new=build/dyn-release \\
      --project ../../dna/src --project tests/performance --compare-output
"""
import argparse, os, random, resource, statistics, subprocess, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]


def run(command, env):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env)
    _, status, usage = os.wait4(process.pid, 0)
    wall = time.perf_counter() - start
    stderr = process.stderr.read().decode(errors='replace')
    process.stderr.close()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = after.ru_utime - before.ru_utime + after.ru_stime - before.ru_stime
    if os.waitstatus_to_exitcode(status):
        sys.exit(f'failed: {" ".join(map(str, command))}\n{stderr}')
    return wall * 1000, cpu * 1000, usage.ru_maxrss / 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--compiler', action='append', required=True, help='NAME=PATH; repeat for each compiler')
    parser.add_argument('--project', action='append', type=Path, required=True)
    parser.add_argument('--mode', default='--release', help='--release, --debug or check')
    parser.add_argument('--samples', type=int, default=11)
    parser.add_argument('--compare-output', action='store_true')
    parser.add_argument('--sdk', type=Path, default=ROOT, help='DYN_SDK for every compiler')
    args = parser.parse_args()
    compilers = []
    for item in args.compiler:
        name, _, path = item.partition('=')
        if not path:
            parser.error('--compiler takes NAME=PATH')
        compilers.append((name, Path(path).resolve()))
    env = dict(os.environ, DYN_SDK=str(args.sdk.resolve()))
    with tempfile.TemporaryDirectory(prefix='dyn-compile-bench-') as work:
        work = Path(work)

        def command(name, compiler, project):
            if args.mode == 'check':
                return [compiler, 'check', project, '--no-cache']
            output = work / f'{name}-{project.name}'
            return [compiler, 'build', project, args.mode, '--no-cache', '--no-link', '--emit-object', '--output', output]

        print(f'{"project":<16} {"compiler":<12} {"wall ms":>9} {"cpu ms":>9} {"rss MiB":>8} {"vs first":>9}')
        for project in args.project:
            project = project.resolve()
            samples = {name: [] for name, _ in compilers}
            for _ in range(args.samples):
                order = compilers[:]
                random.shuffle(order)
                for name, compiler in order:
                    samples[name].append(run(command(name, compiler, project), env))
            first = None
            for name, _ in compilers:
                wall = statistics.median(s[0] for s in samples[name])
                cpu = statistics.median(s[1] for s in samples[name])
                rss = max(s[2] for s in samples[name])
                first = first or wall
                print(f'{project.name:<16} {name:<12} {wall:9.1f} {cpu:9.1f} {rss:8.0f} {wall / first:8.2f}x')
            if args.compare_output and args.mode != 'check':
                objects = {name: (work / f'{name}-{project.name}.o').read_bytes() for name, _ in compilers}
                reference = objects[compilers[0][0]]
                for name, data in objects.items():
                    if data != reference:
                        print(f'{project.name:<16} {name:<12} object differs from {compilers[0][0]}')


if __name__ == '__main__':
    main()
