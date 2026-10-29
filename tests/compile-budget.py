#!/usr/bin/env python3
"""Compile-cost budgets: heap allocations, peak RSS and a coarse wall-time ceiling.

A generated project imports a dozen standard modules and defines generated
functions, then builds in release and debug mode and checks. Allocation
counts and peak RSS barely depend on the host, so their budgets sit 25 percent
above measured values and catch real regressions. Wall time depends on the
runner, so its ceiling only catches gross slowdowns. Allocation counting
preloads a counter and runs on Linux only.

Run with --measure to print current values when updating the budgets.
"""
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
CC = os.environ.get('CC', 'cc').split()
FUNCTIONS = 1500
IMPORTS = ['std/bytes', 'std/strings', 'std/fmt', 'std/encoding/json', 'std/fs', 'std/time',
           'std/math', 'std/sort', 'std/hash', 'std/container/hash table', 'std/unicode/text',
           'std/text plain', 'std/io']
# Measured values; the budget allows 25 percent more. Peak RSS is the highest
# seen on 2 to 32 cores; allocation counts did not vary with the core count.
ALLOCATIONS = {'--release': 179352, '--debug': 47056, 'check': 14727}
PEAK_MIB = {'--release': 91, '--debug': 68, 'check': 39}
WALL_CEILING_MS = 5000
MARGIN = 1.25

COUNTER = r'''
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
static unsigned long calls;
static void *(*real_malloc)(size_t), *(*real_calloc)(size_t, size_t), *(*real_realloc)(void *, size_t);
static char boot[1 << 16];
static size_t boot_used;
void *malloc(size_t n) {
  if (!real_malloc) real_malloc = dlsym(RTLD_NEXT, "malloc");
  __atomic_fetch_add(&calls, 1, __ATOMIC_RELAXED);
  return real_malloc(n);
}
void *calloc(size_t a, size_t b) {
  if (!real_calloc) { void *p = boot + boot_used; boot_used += (a * b + 15) & ~(size_t)15; return p; }
  __atomic_fetch_add(&calls, 1, __ATOMIC_RELAXED);
  return real_calloc(a, b);
}
void *realloc(void *p, size_t n) {
  if (!real_realloc) real_realloc = dlsym(RTLD_NEXT, "realloc");
  __atomic_fetch_add(&calls, 1, __ATOMIC_RELAXED);
  return real_realloc(p, n);
}
void free(void *p) {
  static void (*real_free)(void *);
  if ((char *)p >= boot && (char *)p < boot + sizeof boot) return;
  if (!real_free) real_free = dlsym(RTLD_NEXT, "free");
  real_free(p);
}
__attribute__((constructor)) static void init(void) {
  real_calloc = dlsym(RTLD_NEXT, "calloc");
  real_malloc = dlsym(RTLD_NEXT, "malloc");
  real_realloc = dlsym(RTLD_NEXT, "realloc");
}
__attribute__((destructor)) static void done(void) {
  const char *path = getenv("ALLOCATION_COUNT");
  FILE *f = path ? fopen(path, "w") : NULL;
  if (f) { fprintf(f, "%lu\n", calls); fclose(f); }
}
'''


def project(root):
    gen = root/'gen'
    gen.mkdir(parents=True)
    lines = ['pub struct Point { x: i64, y: i64 }', '']
    for i in range(FUNCTIONS):
        previous = f'f{i - 1}(i % 7, p)' if i else 'i'
        lines += [f'pub fn f{i}(n: i64, p: Point) i64 {{',
                  '  total: i64 = 0',
                  '  for i in 0..n {',
                  f'    if i % 3 == 0 {{ total += {previous} }} else {{ total += i * {i % 13 + 1} + p.x - p.y }}',
                  '  }',
                  f'  return total + {i}',
                  '}', '']
    (gen/'gen.dyn').write_text('\n'.join(lines))
    imports = ''.join(f'use "{module.split()[0]}"{" " + module.split()[1] if " " in module else ""}\n'
                      for module in IMPORTS)
    (root/'main.dyn').write_text(imports + f'''use "./gen" gen

fn main() {{
  p := gen.Point{{x: 3, y: 1}}
  total: i64 = 0
  for i in 0..5 {{ total += gen.f{FUNCTIONS - 1}(#cast(i64, i), p) }}
  _ = total
}}
''')


def measure(mode, source, work, counter):
    output = work/'out'
    command = [DYN, 'check', source, '--no-cache'] if mode == 'check' else \
        [DYN, 'build', source, mode, '--no-cache', '--no-link', '--emit-object', '--output', output]
    env = dict(os.environ, DYN_SDK=str(ROOT))
    count_path = work/'allocations'
    if counter:
        env['LD_PRELOAD'] = str(counter)
        env['ALLOCATION_COUNT'] = str(count_path)
    start = time.perf_counter()
    process = subprocess.Popen(list(map(str, command)), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _, status, usage = os.wait4(process.pid, 0)
    wall = (time.perf_counter() - start) * 1000
    stderr = process.stderr.read().decode(errors='replace')
    process.stderr.close()
    if os.waitstatus_to_exitcode(status):
        sys.exit(f'FAIL compile budget {mode}: compiler failed\n{stderr}')
    peak = usage.ru_maxrss / (1024 * 1024 if platform.system() == 'Darwin' else 1024)
    allocations = int(count_path.read_text()) if counter else None
    return allocations, peak, wall


def main():
    record = '--measure' in sys.argv
    # Sanitizer builds allocate and map far more, and refuse a preloaded
    # allocator; their costs say nothing about the shipped compiler.
    if b'__asan_init' in Path(DYN).read_bytes():
        print('SKIP compile budget: sanitizer-instrumented compiler')
        return
    with tempfile.TemporaryDirectory(prefix='dyn-compile-budget-') as directory:
        work = Path(directory)
        source = work/'project'
        project(source)
        counter = None
        if platform.system() == 'Linux':
            counter = work/'count.so'
            (work/'count.c').write_text(COUNTER)
            subprocess.run([*CC, '-O2', '-shared', '-fPIC', '-o', counter, work/'count.c', '-ldl'], check=True)
        failures = []
        for mode in ALLOCATIONS:
            # The first run warms the file cache.
            measure(mode, source, work, None)
            allocations, peak, wall = measure(mode, source, work, counter)
            print(f'{mode}: allocations {allocations}, peak {peak:.0f} MiB, wall {wall:.0f} ms')
            if record:
                continue
            if allocations is not None and allocations > ALLOCATIONS[mode] * MARGIN:
                failures.append(f'{mode}: {allocations} heap allocations, budget {ALLOCATIONS[mode] * MARGIN:.0f}')
            if peak > PEAK_MIB[mode] * MARGIN:
                failures.append(f'{mode}: {peak:.0f} MiB peak RSS, budget {PEAK_MIB[mode] * MARGIN:.0f}')
            if wall > WALL_CEILING_MS:
                failures.append(f'{mode}: {wall:.0f} ms, ceiling {WALL_CEILING_MS}')
        if failures:
            sys.exit('FAIL compile budget\n' + '\n'.join(failures))
    if not record:
        print('PASS compile budget: heap allocations, peak RSS and wall time')


if __name__ == '__main__':
    main()
