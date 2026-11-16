#!/usr/bin/env python3
"""#sqrt, #floor, #ceil, #trunc, #round and #fma need no import, emit the
instruction where the target has it, and run the compiler's software
elsewhere; the prelude's names are reserved."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"

fn main() {
  a: f64 = 2.0
  b: f32 = 1.5
  io.println("{} {} {} {} {}", #sqrt(a), #floor(-2.5), #ceil(2.1), #trunc(-2.7), #round(2.5))
  io.println("{} {} {}", #fma(a, 3.0, 1.0), #fma(b, b, b), #round(-0.5))
}
'''
EXPECTED = '1.414214 -3 3 -2 3\n7 3.75 -1\n'
with tempfile.TemporaryDirectory(prefix='dyn-math-builtins-') as temporary:
    work = Path(temporary)
    (work / 'ok').mkdir()
    (work / 'ok' / 'main.dyn').write_text(SOURCE)
    for name, flags, emulator in (('debug', ['--debug'], []), ('release', ['--release'], []),
                                  ('native', ['--release', '--cpu', 'native'], []),
                                  ('arm', ['--target', 'aarch64-linux', '--release'], ['qemu-aarch64']),
                                  ('riscv', ['--target', 'riscv64-linux', '--release'], ['qemu-riscv64'])):
        program = work / name
        subprocess.run([DYN, 'build', str(work / 'ok'), *flags, '--no-cache', '--quiet', '--output', str(program)],
                       check=True, timeout=180)
        if emulator and not shutil.which(emulator[0]):
            continue
        output = subprocess.run([*emulator, str(program)], capture_output=True, text=True, check=True, timeout=60).stdout
        assert output == EXPECTED, (name, output)
    if platform.machine() == 'x86_64' and shutil.which('objdump'):
        listing = subprocess.run(['objdump', '-d', '--no-show-raw-insn', str(work / 'release')], capture_output=True,
                                 text=True, check=True).stdout
        main = listing.split('<main>:', 1)[1].split('\n\n', 1)[0]
        assert 'sqrtsd' in main and 'call' in main and 'dyn_builtin_floor' in main, main
    for index, (text, message) in enumerate((
            ('fn main() {\n  _ = #sqrt\n}\n', "expected '(' after a math builtin"),
            ('fn dyn_builtin_sqrt(x: f64) f64 {\n  return x\n}\n\nfn main() {\n}\n', 'belong to the compiler'),
            ('struct DynBuiltinThing { x: i32 }\n\nfn main() {\n}\n', 'belong to the compiler'))):
        bad = work / f'bad{index}'
        bad.mkdir()
        (bad / 'main.dyn').write_text(text)
        checked = subprocess.run([DYN, 'check', str(bad)], capture_output=True, text=True, timeout=60)
        assert checked.returncode != 0 and message in checked.stderr, (text, checked.stderr)
print('PASS math builtins: no import, instructions where present, compiler software elsewhere, reserved names')
