#!/usr/bin/env python3
"""Dense constant tables stay static; sparse huge arrays stay compact."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

DYN = str(Path(os.environ.get('DYN', 'build/dyn')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-constant-table-') as temporary:
    root = Path(temporary)
    count = 8192
    values = [(i * 7919) % 65521 for i in range(count)]
    (root/'tables').mkdir()
    (root/'tables/data.dyn').write_text(
        f'pub const table: [{count}]u32 = [' + ','.join(map(str, values)) + ']\n')
    (root/'main.dyn').write_text(
        'use "./tables" tables\n'
        'snapshot: u32 = tables.table[4096]\n'
        'const sparse: [67108864]u8 = [7]\n'
        'fn main() {\n total: u64 = 0\n for value in tables.table { total += #cast(u64) value }\n'
        f' if total != {sum(values)} {{ #panic("constant table checksum") }}\n'
        f' if snapshot != {values[4096]} {{ #panic("global initialization order") }}\n'
        ' if sparse[0] != 7 || sparse[67108863] != 0 { #panic("sparse zero tail") }\n}\n')
    for mode in ([], ['--release']):
        output = root/'program'
        subprocess.run([DYN, 'build', str(root), '--quiet', '--no-cache', '--emit-ir', '--output', str(output), *mode], check=True)
        ir = output.with_suffix('.ll').read_text()
        if not mode:
            assert re.search(r'constant \[8192 x i32\]', ir), 'dense constant table fell back to runtime stores'
            assert ir.count('global.array.initializer.element') < 10, 'one runtime store per dense constant element'
            assert len(ir) < 300_000, f'IR expanded with array storage size: {len(ir)}'
        subprocess.run([str(output)], check=True, timeout=10)
        # Exercise separate module emission and cache reuse, without --emit-ir.
        for attempt in range(2):
            subprocess.run([DYN, 'build', str(root), '--quiet', '--jobs', '2', '--output', str(root/'cached'), *mode], check=True)
            subprocess.run([str(root/'cached')], check=True, timeout=10)
print('PASS dense constant table static initialization, runtime checksum, 64MiB sparse zero tail, imported/cached, debug/release')
