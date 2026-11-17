#!/usr/bin/env python3
"""Measures native code quality on a fixed set of kernels: release run time
(best of 5), spill slots summed over the program (--opt-remarks), and
instructions that touch the stack frame in the program's own functions.
Writes build/codegen-bench.json; with --compare FILE prints the change
against an earlier run. Run on a quiet machine."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
KERNELS = [ROOT / 'tests/kernels' / n for n in ('nbody', 'sum', 'matmul', 'structs', 'pairs', 'map-small', 'map-large', 'text-case')]
KERNELS += sorted((ROOT / 'tests/codegen-kernels').iterdir())
FLAGS = ['--release'] + sys.argv[sys.argv.index('--flags') + 1].split() if '--flags' in sys.argv else ['--release']


def measure(kernel, work):
    program = work / kernel.name
    remarks = subprocess.run([DYN, 'build', str(kernel), *FLAGS, '--opt-remarks', '--quiet', '--no-cache', '--output', str(program)],
                             capture_output=True, text=True, check=True, timeout=300).stderr
    spills = sum(int(m) for m in re.findall(r'SSA code generation, (\d+) spill slots', remarks))
    listing = work / (kernel.name + '.s')
    subprocess.run([DYN, 'build', str(kernel), *FLAGS, '--emit-asm', '--quiet', '--no-cache', '--output', str(listing)],
                   check=True, timeout=300)
    text = Path(str(listing) + '.s').read_text() if Path(str(listing) + '.s').exists() else listing.read_text()
    stack = instructions = 0
    for line in text.split('\n'):
        m = re.search(r'// \+0x[0-9a-f]+: (.*)', line)
        if m:
            instructions += 1
            stack += '[rbp' in m.group(1) or '[rsp' in m.group(1) or '[sp' in m.group(1) or '[x29' in m.group(1)
    best = None
    output = ''
    for _ in range(5):
        started = time.perf_counter()
        output = subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=300).stdout
        elapsed = time.perf_counter() - started
        best = elapsed if best is None else min(best, elapsed)
    return {'seconds': round(best, 4), 'spill_slots': spills, 'stack_instructions': stack, 'instructions': instructions,
            'output': output.strip()[-60:]}


results = {}
with tempfile.TemporaryDirectory(prefix='dyn-codegen-bench-') as temporary:
    for kernel in KERNELS:
        results[kernel.name] = measure(kernel, Path(temporary))
        r = results[kernel.name]
        print(f"{kernel.name:10} {r['seconds']:8.4f}s  spills {r['spill_slots']:5}  stack {r['stack_instructions']:6} / {r['instructions']}", flush=True)
out = ROOT / 'build/codegen-bench.json'
out.write_text(json.dumps(results, indent=1))
if '--compare' in sys.argv:
    before = json.loads(Path(sys.argv[sys.argv.index('--compare') + 1]).read_text())
    print('\nchange against', sys.argv[sys.argv.index('--compare') + 1])
    for name, r in results.items():
        if name not in before:
            continue
        b = before[name]
        same = 'same output' if b['output'] == r['output'] else 'OUTPUT CHANGED'
        print(f"{name:10} time {r['seconds'] / b['seconds']:6.3f}x  spills {b['spill_slots']:5} -> {r['spill_slots']:5}  "
              f"stack {b['stack_instructions']:6} -> {r['stack_instructions']:6}  {same}")
