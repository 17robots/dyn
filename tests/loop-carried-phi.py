#!/usr/bin/env python3
"""Loop-carried phis spilled for their whole interval live in a register
inside their loop: a counter that calls after the loop push out of registers,
exits through breaks, and a floating counter give the same results at every
level and on every 64-bit target, and the x86-64 loop reads no stack slot."""
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
EXPECTED = '541028 479870\n439098 418712 459484\n231182 228273\n1156 605\n'
# Calls the functions through pointers and keeps their bodies out of callers.
env = dict(os.environ, DYN_NO_INLINE='1')
with tempfile.TemporaryDirectory(prefix='dyn-loop-carried-') as temporary:
    for name, flags, emulator in (('debug', ['--debug'], []), ('release', ['--release'], []),
                                  ('o3', ['--release', '--opt-level', '3'], []),
                                  ('arm', ['--target', 'aarch64-linux', '--release'], ['qemu-aarch64']),
                                  ('riscv', ['--target', 'riscv64-linux', '--release'], ['qemu-riscv64'])):
        program = Path(temporary) / name
        built = subprocess.run([DYN, 'build', str(ROOT / 'tests/loop-carried-phi'), *flags, '--opt-remarks',
                                '--no-cache', '--output', str(program)], capture_output=True, text=True, timeout=120, env=env)
        assert built.returncode == 0, (name, built.stderr)
        # aarch64 and riscv64 have registers enough that nothing spills.
        if name in ('release', 'o3') and platform.machine() == 'x86_64':
            for function in ('scan', 'breaks'):
                assert f'remark: {function}: SSA code generation' in built.stderr, built.stderr
                assert re.search(rf'remark: {function}: SSA code generation, \d+ spill slots, [1-9]\d* loop-cached', built.stderr), \
                    (name, function, built.stderr)
        if emulator and not shutil.which(emulator[0]):
            continue
        result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0 and result.stdout == EXPECTED, (name, result)
        if name == 'release' and platform.system() == 'Linux' and platform.machine() == 'x86_64' and shutil.which('objdump'):
            assembly = subprocess.check_output(['objdump', '-d', '--no-show-raw-insn', str(program)], text=True)
            scan = assembly.split('<scan>:\n')[1].split('\n\n')[0].splitlines()
            # The loop: from the first comparison of the counter to the back edge.
            back = next(i for i, line in enumerate(scan) if re.search(r'\tjb ', line))
            target = scan[back].split()[-2]
            start = next(i for i, line in enumerate(scan) if line.strip().startswith(target + ':'))
            loop = scan[start:back + 1]
            assert not any('(%rbp)' in line for line in loop), ('counter reloaded in the loop', '\n'.join(loop))
print('PASS loop-carried phis')
