#!/usr/bin/env python3
"""Runtime comparison of Dyn release output against cc -O2, Go and Zig.

Each kernel directory holds main.dyn, main.c, main.go and main.zig that print
the same checksum. Reports the median of --samples runs and Dyn's time over
each other build. Zig runs twice: ReleaseFast (no safety checks, like C) and
ReleaseSafe (bounds and overflow checks, closer to Dyn's release builds,
which keep bounds checks). A missing go or zig leaves its columns empty.
"""
import argparse, math, os, shutil, statistics, subprocess, tempfile, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument('--dyn', type=Path, default=ROOT/'build/dyn-release')
p.add_argument('--samples', type=int, default=3)
p.add_argument('kernels', nargs='*')
a = p.parse_args()
kernels = a.kernels or sorted(d.name for d in HERE.iterdir() if (d/'main.dyn').exists())


def timed(command):
    samples = []
    output = None
    for _ in range(a.samples):
        start = time.perf_counter()
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        samples.append(time.perf_counter() - start)
        output = result.stdout.strip()
    return statistics.median(samples), output


def ratio(dyn, other):
    return f'{dyn / other:6.2f}' if not math.isnan(other) else f'{"-":>6}'


with tempfile.TemporaryDirectory(prefix='dyn-bench-') as work:
    work = Path(work)
    have_go, have_zig = shutil.which('go') is not None, shutil.which('zig') is not None
    print(f'{"kernel":<8} {"dyn":>7} {"c -O2":>7} {"go":>7} {"zig":>7} {"zig-s":>7}'
          f' {"/c":>6} {"/go":>6} {"/zig":>6} {"/zig-s":>6}')
    for name in kernels:
        source = HERE/name
        builds = {}
        builds['dyn'] = work/(name+'-dyn')
        subprocess.run([a.dyn, 'build', source, '--release', '--quiet', '--no-cache', '--output', builds['dyn']], check=True)
        builds['c'] = work/(name+'-c')
        subprocess.run([os.environ.get('CC', 'cc'), '-O2', source/'main.c', '-o', builds['c']], check=True)
        if have_go and (source/'main.go').exists():
            builds['go'] = work/(name+'-go')
            subprocess.run(['go', 'build', '-o', builds['go'], source/'main.go'], check=True, cwd=work)
        if have_zig and (source/'main.zig').exists():
            for mode, key in (('ReleaseFast', 'zig'), ('ReleaseSafe', 'zig-s')):
                builds[key] = work/(name+'-'+key)
                subprocess.run(['zig', 'build-exe', source/'main.zig', '-O', mode, f'-femit-bin={builds[key]}'],
                               check=True, cwd=work)
        times, outputs = {}, {}
        for key, binary in builds.items():
            times[key], outputs[key] = timed([binary])
        if len(set(outputs.values())) != 1:
            raise SystemExit(f'{name}: checksums differ: {outputs}')
        t = {key: times.get(key, float('nan')) for key in ('dyn', 'c', 'go', 'zig', 'zig-s')}
        print(f'{name:<8} {t["dyn"]:7.3f} {t["c"]:7.3f} {t["go"]:7.3f} {t["zig"]:7.3f} {t["zig-s"]:7.3f}'
              f' {ratio(t["dyn"], t["c"])} {ratio(t["dyn"], t["go"])} {ratio(t["dyn"], t["zig"])} {ratio(t["dyn"], t["zig-s"])}',
              flush=True)
