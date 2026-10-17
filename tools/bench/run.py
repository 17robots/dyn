#!/usr/bin/env python3
"""Runtime comparison of Dyn release output against cc -O2 and Go.

Each kernel directory holds main.dyn, main.c and main.go that print the same
checksum. Reports the median of --samples runs and the Dyn/C and Dyn/Go ratios.
"""
import argparse, os, shutil, statistics, subprocess, tempfile, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--dyn', type=Path, default=ROOT/'build/dyn-release')
p.add_argument('--samples', type=int, default=3)
p.add_argument('kernels', nargs='*')
a = p.parse_args()
kernels = a.kernels or sorted(d.name for d in HERE.iterdir() if (d/'main.dyn').exists())
def timed(command):
    best = []
    output = None
    for _ in range(a.samples):
        start = time.perf_counter()
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        best.append(time.perf_counter() - start)
        output = result.stdout.strip()
    return statistics.median(best), output
with tempfile.TemporaryDirectory(prefix='dyn-bench-') as work:
    work = Path(work)
    print(f'{"kernel":<8} {"dyn":>8} {"c -O2":>8} {"go":>8} {"dyn/c":>6} {"dyn/go":>6} {"size":>8}')
    for name in kernels:
        source = HERE/name
        dyn, c, go = work/(name+'-dyn'), work/(name+'-c'), work/(name+'-go')
        subprocess.run([a.dyn, 'build', source, '--release', '--quiet', '--no-cache', '--output', dyn], check=True)
        subprocess.run([os.environ.get('CC', 'cc'), '-O2', source/'main.c', '-o', c], check=True)
        have_go = shutil.which('go') is not None
        if have_go:
            subprocess.run(['go', 'build', '-o', go, source/'main.go'], check=True, cwd=work)
        dt, do = timed([dyn])
        ct, co = timed([c])
        gt, go_out = timed([go]) if have_go else (float('nan'), do)
        if not (do == co == go_out):
            raise SystemExit(f'{name}: checksums differ: dyn {do} c {co} go {go_out}')
        print(f'{name:<8} {dt:8.3f} {ct:8.3f} {gt:8.3f} {dt/ct:6.2f} {dt/gt:6.2f} {dyn.stat().st_size:8}')
