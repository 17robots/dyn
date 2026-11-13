#!/usr/bin/env python3
"""sort.sort_by and sort.stable_by against Python's stable sorted(): random
records with duplicate keys, sizes around the insertion and heap cut-offs,
debug and release. stable_by must also keep equal keys in input order."""
import os
from pathlib import Path
import random
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
generator = random.Random(0x5057)
cases = []
for size in (0, 1, 2, 15, 16, 17, 100, 1000):
    keys = [generator.randrange(0, max(1, size // 3)) for _ in range(size)]
    cases.append(keys)
lines = ['use "std/io"', 'use "std/mem"', 'use "std/sort"', '',
         'struct Record { key: i32, order: i32 }',
         'fn by_key(a: Record, b: Record) bool { return a.key < b.key }', '',
         'fn check(records: []Record) {',
         '  for record, i in records { io.print("{}:{} ", record.key, record.order) }', '  io.println("")', '}', '',
         'fn main() {', '  arena := mem.arena_alloc(0)']
expected = []
for index, keys in enumerate(cases):
    records = ', '.join(f'Record{{key: {key}, order: {order}}}' for order, key in enumerate(keys))
    lines.append(f'  stable_{index}: [{len(keys)}]Record' + (f' = [{records}]' if keys else ''))
    lines.append(f'  sort.stable_by(arena, stable_{index}[..], by_key)')
    lines.append(f'  check(stable_{index}[..])')
    lines.append(f'  plain_{index}: [{len(keys)}]Record' + (f' = [{records}]' if keys else ''))
    lines.append(f'  sort.sort_by(plain_{index}[..], by_key)')
    lines.append(f'  for record in plain_{index} {{ io.print("{{}} ", record.key) }}')
    lines.append('  io.println("")')
    ordered = sorted(enumerate(keys), key=lambda pair: pair[1])
    expected.append(''.join(f'{key}:{order} ' for order, key in ordered))
    expected.append(''.join(f'{key} ' for _, key in ordered))
lines += ['  // The scratch copy is rewound: the arena is back where it started.',
          '  if mem.arena_mark(arena) != mem.arena_start(arena) { #panic("stable_by kept its scratch") }', '}']
with tempfile.TemporaryDirectory(prefix='dyn-sort-by-') as temporary:
    work = Path(temporary)
    (work / 'main.dyn').write_text('\n'.join(lines) + '\n')
    for mode in ('--debug', '--release'):
        output = work / mode.strip('-')
        subprocess.run([DYN, 'build', str(work), mode, '--no-cache', '--quiet', '--output', str(output)],
                       check=True, timeout=120)
        result = subprocess.run([str(output)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        assert result.stdout.split('\n')[:-1] == expected, (mode, result.stdout[:400])
print(f'PASS sort_by and stable_by: {len(cases)} sizes match Python sorted(), stable order kept (debug/release)')
