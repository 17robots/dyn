#!/usr/bin/env python3
"""SSA load and store combining: x[0] | x[1] << 8 | ... from consecutive
addresses is one load, and stores of x, x >> 8, ... one store, on x86-64 and
AArch64. Results match debug and O3; the release listing keeps no byte
loads or stores for the word-sized accesses."""
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-native-combine-') as temporary:
    work = Path(temporary)
    outputs = []
    for flags in (['--debug'], ['--release'], ['--release', '--opt-level', '3']):
        program = work / 'program'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/native-combine'), *flags, '--quiet', '--no-cache', '--output', str(program)],
                       check=True, timeout=180)
        outputs.append(subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=30).stdout)
    assert outputs[0] == outputs[1] == outputs[2], outputs
    assert outputs[0].split()[1:] == ['3735928559', '4660', '67305985'], outputs[0]
    if platform.machine() in ('x86_64', 'AMD64'):
        listing = work / 'program.s'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/native-combine'), '--release', '--quiet', '--no-cache', '--emit-asm',
                        '--output', str(listing)], check=True, timeout=180)
        text = (work / 'program.s.s').read_text() if (work / 'program.s.s').exists() else listing.read_text()
        # main and every emitted binary.load_*/store_* helper: no byte access
        # left for the word-sized ones (main keeps none, the helpers none).
        functions = re.findall(r'\n"([^"\n]*(?:main|_(?:load|store)_u(?:16|32|64)_le))":\n(.*?)(?=\n"|\Z)', text, re.S)
        assert any(name == 'main' for name, _ in functions), [name for name, _ in functions]
        for name, body in functions:
            ops = [m.group(1) for m in re.finditer(r'// \+0x[0-9a-f]+: (.*)', body)]
            byte_loads = sum(op.startswith('movzx') and 'byte ptr' in op for op in ops)
            byte_stores = sum(op.startswith('mov byte ptr') for op in ops)
            assert byte_loads == 0 and byte_stores == 0, (name, byte_loads, byte_stores)
print('PASS native load/store combining: one access per word (debug/release/O3)')
