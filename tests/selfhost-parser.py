#!/usr/bin/env python3
"""The Dyn port of the source parser matches the C parser node for node."""
import os
from pathlib import Path
import random
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
CC = shlex.split(os.environ.get('CC', 'cc'))
PIECES = [b'{', b'}', b'(', b')', b'[', b']', b'.', b'..', b'...', b',', b':', b'=', b'"', b"'",
          b'#', b'$', b'*', b'\n', b' ', b'0x', b'1.', b'/*', b'\\', b'\xff', b'\xe0\x80',
          b'if ', b'for ', b'case ', b'fn ', b'x', b'\x0b', b'\x00', b'..=', b'=>',
          b'#reverse(', b'#cast(']

corpus = sorted(path for directory in ('std', 'runtime', 'vendor', 'tests')
                for path in (ROOT / directory).rglob('*.dyn'))
with tempfile.TemporaryDirectory(prefix='dyn-selfhost-parser-') as temporary:
    work = Path(temporary)
    oracle = work / 'oracle'
    program = work / 'parser'
    subprocess.run([*CC, '-O2', '-o', str(oracle), str(ROOT / 'tests/selfhost-parser-oracle.c'),
                    str(ROOT / 'src/parser.c')], check=True, timeout=120)
    subprocess.run([DYN, 'build', str(ROOT / 'tests/selfhost-parser'), '--release', '--no-cache',
                    '--quiet', '--output', str(program)], check=True, timeout=180)
    generated = {
        'empty.dyn': b'',
        'nested-groups.dyn': b'fn f() { x := ' + b'(' * 1100 + b'1' + b')' * 1100 + b' }\n',
        'nested-blocks.dyn': b'fn f() ' + b'{ if true ' * 600 + b'{}' + b' }' * 600 + b'\n',
        'too-deep-blocks.dyn': b'fn f() ' + b'{ if true ' * 1100 + b'{}' + b' }' * 1100 + b'\n',
        'nested-types.dyn': b'x: ' + b'*' * 1100 + b'u8\n',
        'long-chain.dyn': b'fn f() { x := 1' + b' + 1' * 20000 + b' }\n',
        'nul.dyn': b'fn f() {}\n\x00',
    }
    random.seed(17)
    for index in range(600):
        source = random.choice(corpus).read_bytes()
        for _ in range(random.randint(1, 3)):
            at = random.randint(0, len(source))
            choice = random.random()
            if choice < 0.3:
                source = source[:at]
            elif choice < 0.6:
                source = source[:at] + source[at + random.randint(1, 8):]
            else:
                source = source[:at] + random.choice(PIECES) + source[at:]
        generated[f'mutant-{index}.dyn'] = source
    paths = [str(path) for path in corpus]
    for name, data in generated.items():
        (work / name).write_bytes(data)
        paths.append(str(work / name))
    expected = subprocess.run([str(oracle), *paths], check=True, capture_output=True, timeout=120).stdout
    actual = subprocess.run([str(program), *paths], check=True, capture_output=True, timeout=120).stdout
    if actual != expected:
        for line, (left, right) in enumerate(zip(expected.splitlines(), actual.splitlines()), 1):
            if left != right:
                raise SystemExit(f'line {line}: C {left!r}, Dyn {right!r}')
        raise SystemExit('dump lengths differ')
print(f'PASS self-hosted parser matches C parser on {len(corpus)} sources and {len(generated)} generated inputs')
