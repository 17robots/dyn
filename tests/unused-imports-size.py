#!/usr/bin/env python3
"""Unused imports cost nothing: debug and release executables keep only the
functions and globals that main reaches, so importing modules a program never
calls leaves the loaded code and data the same size. A global whose
initializer calls a function stays, since that call may have effects."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())

def build(directory, source, flags):
    (directory / 'main.dyn').write_text(source)
    output = directory / 'program'
    result = subprocess.run([DYN, 'build', str(directory), *flags, '--quiet', '--no-cache', '--output', str(output)],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    run = subprocess.run([str(output)], capture_output=True, text=True, timeout=60)
    return loaded_bytes(output), run.stdout

# Code and data the program loads; debug line tables name each source file
# and so vary by a few bytes with the import list.
def loaded_bytes(path):
    sections = subprocess.run(['readelf', '-S', '-W', str(path)], capture_output=True, text=True).stdout
    total = 0
    for line in sections.splitlines():
        fields = line.replace('[ ', '[').split()
        if len(fields) > 7 and fields[0].startswith('[') and 'A' in fields[7]:
            total += int(fields[5], 16)
    return total

plain = 'use "std/io"\n\nfn main() {\n  io.println("hi")\n}\n'
extra = ('use "std/io"\nuse "std/container/map"\nuse "std/fs"\nuse "std/process"\nuse "std/text"\nuse "std/time"\n\n'
         'fn main() {\n  io.println("hi")\n}\n')
effects = ('use "std/io"\n\ncounter: i32 = 0\ntouched: i32 = touch()\nconst unused_table: [4]i64 = [1, 2, 3, 4]\n\n'
           'fn touch() i32 {\n  io.println("init")\n  return 1\n}\n\nfn main() {\n  io.println("hi")\n}\n')
with tempfile.TemporaryDirectory(prefix='dyn-unused-') as directory:
    work = Path(directory)
    for flags in ([], ['--release']):
        a = build(work, plain, flags)
        b = build(work, extra, flags)
        assert a == b and a[1] == 'hi\n', (flags, a, b)
        size, out = build(work, effects, flags)
        assert out == 'init\nhi\n', (flags, out)
print('PASS unused imports and globals add nothing to debug or release executables')
