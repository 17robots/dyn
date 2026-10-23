#!/usr/bin/env python3
"""Paired independent O2/O3 runtime measurements with checked dynamic results.

No timing threshold or optimizer parity claim. Both artifacts use one compiler,
identical input and runtime objects. Trials alternate order to reduce drift.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess

from benchmark import measure

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--dyn', type=Path, default=ROOT/'build/dyn-release')
p.add_argument('--samples', type=int, default=7)
p.add_argument('--iterations', type=int, default=50000000)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--kernel', choices=('calls', 'vector'), default='calls')
a = p.parse_args()
if a.samples < 1 or not 1 <= a.iterations <= 100000000:
    p.error('positive samples and iterations in 1..100000000 required')
if a.output.exists():
    p.error('output must be a new directory')
a.output.mkdir(parents=True)
work = a.output.resolve()
compiler = a.dyn.resolve()
env = dict(os.environ, DYN_SDK=str(ROOT), DYN_CACHE_DIR=str(work/'cache'))
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
compiler_hash = digest(compiler)
runtime_dirs = [compiler.parent, compiler.parent.parent/'lib/dyn']
runtimes = {str(f.resolve()): digest(f) for d in runtime_dirs for f in d.glob('dynrt*.o')}
# Each call has dynamic arguments and multiple returns. The O2 constant
# evaluator cannot replace it. The final checksum checks every executed step.
expected = (a.iterations * 3) % 100003
source = f'''fn step(value: i64) i64 {{
  next := value + 3
  if next >= 100003 {{ return next - 100003 }}
  return next
}}
fn main() {{
  value: i64 = 0
  for i in 0..{a.iterations} {{ value = step(value) }}
  if value != {expected} {{ #panic("benchmark checksum") }}
}}
'''
if a.kernel == 'vector':
    rounds = max(1, a.iterations // 1027)
    expected = None
    source = f'''fn main() {{
  a: [1027]u32 = [] b: [1027]u32 = []
  for i in 0..1027 {{ a[i] = #cast(u32, i) b[i] = (#cast(u32, i)) * 3 }}
  for round in 0..{rounds} {{
    for i in 0..1027 {{ a[i] = #wrap(a[i] + b[i]) }}
  }}
  for i in 0..1027 {{
    expected := #wrap((#cast(u32, i)) + (#cast(u32, {rounds})) * ((#cast(u32, i)) * 3))
    if a[i] != expected {{ #panic("vector benchmark checksum") }}
  }}
}}
'''
module = work/'src' 
module.mkdir()
(module/'main.dyn').write_text(source)
records = {}
for level in (2, 3):
    output = work/(f'o{level}.exe' if os.name == 'nt' else f'o{level}')
    command = [str(compiler), 'build', str(module), '--release', '--opt-level', str(level),
               '--no-cache', '--opt-remarks', '--emit-object', '--output', str(output)]
    built = measure(command, env, 120)
    if level == 3:
        if a.kernel == 'calls':
            counts = re.findall(r'(\d+) direct calls inlined', built['stderr'])
            assert sum(map(int, counts)) > 0, built['stderr']
        else:
            assert 'vectorized 1027 integer elements' in built['stderr'], built['stderr']
    measure([str(output)], env, 120)
    records[str(level)] = dict(command=command, build=built, artifact=str(output),
        artifact_sha256=digest(output), artifact_bytes=output.stat().st_size,
        object_bytes=Path(str(output)+'.o').stat().st_size, samples=[])
    objdump = shutil.which('objdump')
    if objdump and platform.machine().lower() in ('x86_64', 'amd64'):
        disassembly = subprocess.run([objdump, '-d', str(output)+'.o'], text=True, capture_output=True, check=True).stdout
        records[str(level)]['frame_memory_references'] = len(re.findall(r'\(%rbp\)', disassembly))
        records[str(level)]['disassembler'] = objdump
        (work/f'o{level}.disassembly').write_text(disassembly)
for trial in range(a.samples):
    for level in ((2, 3) if trial % 2 == 0 else (3, 2)):
        record = records[str(level)]
        row = measure([record['artifact']], env, 120)
        row['trial'] = trial
        record['samples'].append(row)
assert digest(compiler) == compiler_hash, 'compiler changed during measurements'
assert all(digest(Path(path)) == value for path, value in runtimes.items()), 'runtime changed during measurements'
assert len({sample['stdout_sha256'] for row in records.values() for sample in row['samples']}) == 1
for record in records.values():
    record['median_seconds'] = statistics.median(row['seconds'] for row in record['samples'])
result = dict(platform=platform.platform(), compiler=str(compiler), compiler_sha256=compiler_hash,
    source_sha256=hashlib.sha256(source.encode()).hexdigest(), runtime_sha256=runtimes,
    tool_sha256={str(f.relative_to(ROOT)): digest(f) for f in (Path(__file__).resolve(), ROOT/'tools/benchmark.py')},
    kernel=a.kernel, iterations=a.iterations, expected_checksum=expected, variants=records,
    o2_over_o3=records['2']['median_seconds']/records['3']['median_seconds'],
    scope='Paired kernel measurements only; no general performance parity claim.')
(work/'results.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps({k: result[k] for k in ('kernel', 'iterations', 'expected_checksum', 'o2_over_o3', 'scope')}, indent=2))
