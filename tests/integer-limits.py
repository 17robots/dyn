#!/usr/bin/env python3
"""#max(T) and #min(T) are constants of T on every target, and #syscall takes
a named constant from std/os/linux/sys on targets that map numbers."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
EXPECTED = ('18446744073709551615 -9223372036854775808 2147483647 -128\n255 0 true\ntrue\n'
            'true 4294967295\n')
with tempfile.TemporaryDirectory(prefix='dyn-integer-limits-') as temporary:
    for name, flags, emulator in (('debug', ['--debug'], []), ('release', ['--release'], []),
                                  ('arm', ['--target', 'aarch64-linux', '--release'], ['qemu-aarch64']),
                                  ('riscv', ['--target', 'riscv64-linux'], ['qemu-riscv64'])):
        program = Path(temporary) / name
        built = subprocess.run([DYN, 'build', str(ROOT / 'tests/integer-limits'), *flags, '--no-cache',
                                '--output', str(program)], capture_output=True, text=True, timeout=120)
        assert built.returncode == 0, (name, built.stderr)
        if emulator and not shutil.which(emulator[0]):
            continue
        result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0 and result.stdout == EXPECTED, (name, result)
    project = Path(temporary) / 'bad'
    project.mkdir()
    (project / 'main.dyn').write_text('fn main() {\n  _ = #max(f64)\n}\n')
    bad = subprocess.run([DYN, 'check', str(project)], capture_output=True, text=True, timeout=60)
    assert bad.returncode != 0 and '#max requires an integer type' in bad.stderr, bad
print('PASS integer limits and named syscalls')
