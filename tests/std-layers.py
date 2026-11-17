#!/usr/bin/env python3
"""std/layers.txt names the layer of every std module, and the layers hold:
core imports only core, heap only core and heap, and every core and heap
module checks for the bare-metal targets riscv64-none, riscv32-none and
thumbv7em-none. Imports in files for one operating system do not count:
bare-metal builds never compile them."""
import concurrent.futures
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
TARGETS = ('riscv64-none', 'riscv32-none', 'thumbv7em-none')
ORDER = {'core': 0, 'heap': 1, 'std': 2}

layers = {}
for number, line in enumerate((ROOT / 'std/layers.txt').read_text().splitlines(), 1):
    if not line.strip() or line.startswith('#'):
        continue
    layer, module = line.split()
    assert layer in ORDER, (number, line)
    assert module not in layers, f'std/layers.txt lists {module} twice'
    layers[module] = layer
modules = sorted({path.parent.relative_to(ROOT).as_posix() for path in (ROOT / 'std').rglob('*.dyn')})
missing = [module for module in modules if module not in layers]
assert not missing, f'std/layers.txt is missing {missing}'
stale = [module for module in layers if module not in modules]
assert not stale, f'std/layers.txt lists modules that do not exist: {stale}'


def bare_metal(path):
    directive = re.search(r'^#target\((.*)\)', path.read_text(), re.M)
    kernel = directive and re.search(r'kernel:\s*(\w+)', directive.group(1))
    return not kernel or kernel.group(1) == 'none'


problems = []
for module, layer in layers.items():
    if layer == 'std':
        continue
    for path in sorted((ROOT / module).glob('*.dyn')):
        if not bare_metal(path):
            continue
        for use in re.findall(r'^use .*$', path.read_text(), re.M):
            for imported in re.findall(r'"((?:std|vendor)/[^"]+)"', use):
                if ORDER[layers.get(imported, 'std')] > ORDER[layer]:
                    problems.append(f'{module} ({layer}) imports {imported} ({layers.get(imported, "vendor")})'
                                    f' in {path.name}')
assert not problems, '\n'.join(problems)


def check(job):
    module, target = job
    result = subprocess.run([DYN, 'check', str(ROOT / module), '--target', target],
                            capture_output=True, text=True, timeout=300)
    return module, target, result.returncode, result.stderr


jobs = [(module, target) for module, layer in layers.items() if layer != 'std' for target in TARGETS]
with concurrent.futures.ThreadPoolExecutor(max(1, min(16, os.cpu_count() or 1))) as pool:
    failures = [f'{module} on {target}: {stderr.strip().splitlines()[0] if stderr.strip() else code}'
                for module, target, code, stderr in pool.map(check, jobs) if code]
assert not failures, '\n'.join(failures)
counts = {layer: sum(value == layer for value in layers.values()) for layer in ORDER}
print(f"PASS std layers: {counts['core']} core and {counts['heap']} heap modules check on "
      f"{', '.join(TARGETS)} and import only lower layers; {counts['std']} std modules")
