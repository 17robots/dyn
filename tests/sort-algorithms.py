#!/usr/bin/env python3
"""Independent Python sort oracles, opaque inputs, and bounded introsort cases.

C only transports input and compares results; Python computes every expected
order. This checks correctness, not performance. NaNs are outside sort's strict
weak ordering contract. No comparator overload exists for user structs.
"""
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
ENV = {**os.environ, 'DYN_SDK': str(ROOT)}
ENV.pop('DYN_NO_SSA', None)
C = r'''
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint64_t input[65536], expected[65536];
static size_t count;
intptr_t next_case(int kind) {
  int actual; long long signed_n; size_t n;
  if (scanf("%d %lld", &actual, &signed_n) != 2) return -1;
  if (signed_n < 0) return -1;
  n = (size_t)signed_n;
  if (actual != kind || n > 65536) abort();
  count = n;
  for (size_t i=0;i<n;i++) if (scanf("%" SCNx64, &input[i]) != 1) abort();
  for (size_t i=0;i<n;i++) if (scanf("%" SCNx64, &expected[i]) != 1) abort();
  return (intptr_t)n;
}
void fill_u32(uint32_t *out) { for(size_t i=0;i<count;i++) out[i]=(uint32_t)input[i]; }
void fill_i64(int64_t *out) { memcpy(out,input,count*8); }
void fill_f64(double *out) { memcpy(out,input,count*8); }
void check_u32(uint32_t *out) { for(size_t i=0;i<count;i++) if(out[i]!=expected[i]) abort(); }
void check_i64(int64_t *out) { if(memcmp(out,expected,count*8)) abort(); }
static uint64_t actual_bits[65536], original_bits[65536];
static int compare_bits(const void *a, const void *b) {
  uint64_t x, y; memcpy(&x,a,8); memcpy(&y,b,8);
  return (x > y) - (x < y);
}
void check_f64(double *out) {
#ifdef CORRUPT_NEGATIVE_ZERO
  /* Temporary negative control: numeric equality alone accepts this change. */
  for(size_t i=0;i<count;i++) {
    uint64_t bits; memcpy(&bits,&out[i],8);
    if(bits == UINT64_C(0x8000000000000000)) {
      bits=0; memcpy(&out[i],&bits,8);
    }
  }
#endif
  for(size_t i=0;i<count;i++) {
    double want; memcpy(&want,&expected[i],8);
    if(out[i]!=want) abort();
  }
  /* Compare exact permutations independently of numeric ordering. Equal
     floating values may move freely, but every input bit pattern survives. */
  memcpy(actual_bits,out,count*8);
  memcpy(original_bits,input,count*8);
  qsort(actual_bits,count,8,compare_bits);
  qsort(original_bits,count,8,compare_bits);
  if(memcmp(actual_bits,original_bits,count*8)) exit(73);
}
'''
SOURCE = '''use "std/sort"
extern fn next_case(kind: i32) isize
extern fn fill_u32(out: *u32)
extern fn fill_i64(out: *i64)
extern fn fill_f64(out: *f64)
extern fn check_u32(out: *u32)
extern fn check_i64(out: *i64)
extern fn check_f64(out: *f64)
'''
for kind, typ in enumerate(('u32', 'i64', 'f64')):
    SOURCE += f'''fn test_{typ}() {{
    storage: [65536]{typ}
    for {{
      length := next_case({kind})
      if length < 0 {{ break }}
      count := #cast(usize, length)
      fill_{typ}(&storage[0])
      sort.sort(storage[..count])
      check_{typ}(&storage[0])
    }}
}}
'''
SOURCE += '''fn main() {
  test_u32()
  test_i64()
  test_f64()
  search_values: [5]i32 = [-9, -2, 0, 4, 4]
  for missing in [-10, -8, 1, 5] {
    result := sort.search(search_values[..], missing)
    if result.found || result.index != 5 { #panic("search miss") }
  }
  result := sort.search(search_values[..], 4)
  if !result.found || result.index != 3 { #panic("search first duplicate") }
}
'''


def distributions(n, rng):
    ordered = list(range(n))
    yield ordered
    yield ordered[::-1]
    yield [7] * n
    yield [i % 5 for i in ordered]
    yield [min(i, n - i) for i in ordered]  # organ pipe
    yield [(i * 37) % max(1, n) for i in ordered]  # sawtooth/permutation
    shuffled = ordered[:]
    rng.shuffle(shuffled)
    yield shuffled
    if n:
        ordered[n // 2] = 0
    yield ordered  # almost sorted
    # Full-prefix detection must still inspect the last adjacent pair.
    if n >= 3:
        late_ascending = list(range(n))
        late_ascending[-1] = 0
        yield late_ascending
        late_descending = list(range(n - 1, -1, -1))
        late_descending[-1] = n
        yield late_descending
    # Equal runs are monotone despite equivalent adjacent keys.
    yield [i // 7 for i in range(n)]
    yield [i // 7 for i in range(n - 1, -1, -1)]
    # Median-of-three killer family: interleaved low/high odd values,
    # followed by evens. The introspection depth must cap bad partitions.
    if n >= 4 and n % 4 == 0:
        half = n // 2
        yield [v for i in range(1, half, 2) for v in (i, half + i)] + list(range(2, n + 1, 2))
    yield [rng.getrandbits(32) for _ in range(n)]


def bits(value, kind):
    if kind == 2:
        return struct.unpack('<Q', struct.pack('<d', value))[0]
    return value & ((1 << 64) - 1)


rng = random.Random(0xD1FF2025)
by_kind = [[] for _ in range(3)]
for kind in range(3):
    for n in (0, 1, 2, 3, 7, 15, 16, 17, 31, 32, 63, 64,
              127, 255, 256, 1024, 4096, 32768, 65536):
        for values in distributions(n, rng):
            if kind == 1:
                values = [v - (1 << 31) for v in values]
                if n > 1:
                    values[0], values[-1] = -(1 << 63), (1 << 63) - 1
            elif kind == 2:
                values = [float(v) / 8 - 100 for v in values]
                if n > 1:
                    values[0], values[-1] = float('-inf'), float('inf')
            by_kind[kind].append(values)
# Preserve genuinely descending signed and floating samples: the broad
# generator also injects endpoint extremes, which can break monotonicity.
by_kind[1].append([(1 << 63) - 1] + list(range(63, -1, -1)) + [-(1 << 63)])
by_kind[1].append(list(range(-64, 0)) + [-65])
by_kind[1].append(list(range(64, 0, -1)) + [65])
by_kind[2].append(list(map(float, range(64))) + [-1.0])
by_kind[2].append(list(map(float, range(64, 0, -1))) + [65.0])
by_kind[2].append([0.0, -0.0, -1.0, 1.0] * 16)
by_kind[2].append([-1.0] * 8 + [0.0, -0.0] * 16 + [1.0] * 8)
by_kind[2].append([1.0] * 8 + [-0.0, 0.0] * 16 + [-1.0] * 8)
by_kind[2].append([0.0, -0.0] * 64)

cc = shutil.which(os.environ.get('CC', 'cc'))
if not cc:
    raise SystemExit('SKIP sort-algorithms: C compiler unavailable')
libc = subprocess.run([cc, '-print-file-name=libc.so.6'], capture_output=True, text=True, check=True, timeout=30).stdout.strip()
if not Path(libc).is_file():
    raise SystemExit('SKIP sort-algorithms: host libc unavailable')
with tempfile.TemporaryDirectory(prefix='dyn-sort-algorithms-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE)
    (work / 'oracle.c').write_text(C)
    subprocess.run([cc, '-O2', '-c', str(work / 'oracle.c'), '-o', str(work / 'oracle.o')],
                   check=True, timeout=30)
    lines = []
    for kind, cases in enumerate(by_kind):
        for values in cases:
            lines += [f'{kind} {len(values)}',
                      ' '.join(f'{bits(v, kind):x}' for v in values),
                      ' '.join(f'{bits(v, kind):x}' for v in sorted(values))]
        lines.append(f'{kind} -1')
    data = '\n'.join(lines).encode()
    # Expose the private entry only in a disposable module. Forced depths
    # exercise heap fallback and partition-then-heap independently of whether
    # a particular adversarial permutation reaches the public depth budget.
    probe = work / 'probe'
    probe.mkdir()
    (probe / 'probe.dyn').write_text((ROOT / 'std/sort/sort.dyn').read_text().replace(
        'fn introsort(', 'pub fn introsort('))
    for mode, extra in (('debug', ['--debug']), ('release', ['--release']),
                        ('release-tree', ['--release']),
                        ('heap-depth0', ['--release']), ('heap-depth1', ['--release'])):
        if mode.startswith('heap-depth'):
            depth = int(mode[-1])
            (work / 'main.dyn').write_text(SOURCE.replace('use "std/sort"',
                'use "std/sort"\nuse "probe"').replace(
                'sort.sort(storage[..count])', f'probe.introsort(storage[..count], {depth})'))
        else:
            (work / 'main.dyn').write_text(SOURCE)
        env = dict(ENV)
        if mode.endswith('tree'):
            env['DYN_NO_SSA'] = '1'
        output = work / mode
        subprocess.run([DYN, 'build', str(work), *extra, '--quiet', '--no-cache',
                        '--link', str(work / 'oracle.o'), '--link', libc, '--output', str(output)],
                       env=env, check=True, timeout=120)
        result = subprocess.run([str(output)], input=data, env=env,
                                capture_output=True, timeout=90)
        assert result.returncode == 0, (mode, result.returncode, result.stderr.decode())
        assert not result.stdout and not result.stderr, (mode, result.stdout, result.stderr)
        print(f'PASS sort algorithms {mode}: {sum(map(len, by_kind))} Python oracle cases', flush=True)

    # Link a disposable corrupted checker into normal Dyn programs. The
    # numeric oracle still accepts changed zero signs; permutation must reject.
    subprocess.run([cc, '-O2', '-DCORRUPT_NEGATIVE_ZERO', '-c', str(work / 'oracle.c'),
                    '-o', str(work / 'corrupt.o')], check=True, timeout=30)
    (work / 'main.dyn').write_text(SOURCE)
    for mode in ('debug', 'release'):
        output = work / ('negative-' + mode)
        subprocess.run([DYN, 'build', str(work), '--' + mode, '--quiet', '--no-cache',
                        '--link', str(work / 'corrupt.o'), '--link', libc,
                        '--output', str(output)], env=ENV, check=True, timeout=120)
        result = subprocess.run([str(output)], input=data, env=ENV,
                                capture_output=True, timeout=90)
        assert result.returncode == 73, (mode, result.returncode, result.stderr.decode())
        assert not result.stdout and not result.stderr
        print('PASS sort signed-zero permutation negative control ' + mode, flush=True)
