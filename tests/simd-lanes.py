#!/usr/bin/env python3
"""128-bit lanes: scalar oracle, per-lane wrap, float arithmetic and native SIMD."""
import os
import platform
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
source = ['use "std/simd" simd\nfn check(ok: bool) { if !ok { #panic("SIMD lanes") } }\nfn main() {']
for t, n in [('u8',16), ('i8',16), ('u16',8), ('i16',8), ('u32',4), ('i32',4), ('u64',2), ('i64',2), ('f32',4), ('f64',2)]:
    prefix = t+'x'+str(n)
    typename = t[0].upper()+t[1:]+'x'+str(n)
    # Separate blocks allow concrete lane types with the same variable names.
    source.append('if true {\n  a: simd.'+typename+' = []\n  b: simd.'+typename+' = []')
    source.append(f'  for i in 0..{n} {{\n    a[i] = #cast({t}, i + 1)\n    b[i] = #cast({t}, i + 2)\n  }}')
    source.append(f'  check(#sizeof(simd.{typename}) == 16)')
    for operation, symbol in [('add','+'), ('sub','-'), ('mul','*')]+([('div','/')] if t[0]=='f' else [('and','&'), ('or','|'), ('xor','^')]):
        oracle = f'a[i] {symbol} b[i]'
        if t[0]!='f' and operation in ('add','sub','mul'):
            oracle = f'#wrap({oracle})'
        source.append(f'  {operation} := simd.{prefix}_{operation}(a, b)\n  for i in 0..{n} {{ check({operation}[i] == {oracle}) }}')
    source.append(f'  copy := simd.{prefix}_load(a[..])\n  destination: [{n+2}]{t} = []\n  simd.{prefix}_store(destination[1..], copy)\n  check(destination[0] == 0 && destination[{n+1}] == 0)\n  for i in 0..{n} {{ check(destination[i+1] == a[i]) }}')
    if t[0]!='f':
        max_value = (1 << int(t[1:]))-1 if t[0]=='u' else (1 << (int(t[1:])-1))-1
        source.append(f'  maximum := simd.{prefix}_splat({max_value})\n  one := simd.{prefix}_splat(1)\n  overflow := simd.{prefix}_add(maximum, one)\n  product := simd.{prefix}_mul(maximum, maximum)\n  for i in 0..{n} {{ check(overflow[i] == #wrap(maximum[i] + one[i]) && product[i] == #wrap(maximum[i] * maximum[i])) }}')
        source.append(f'  b[0] = a[0]\n  mask := simd.{prefix}_equal(a,b)\n  selected := simd.{prefix}_select(mask, a, b)\n  check(mask[0] == ~#cast({t}, 0))\n  for i in 1..{n} {{ check(mask[i] == 0 && selected[i] == b[i]) }}')
        source.append(f'  five := simd.{prefix}_splat(5)\n  nine := simd.{prefix}_splat(9)\n  chosen := simd.{prefix}_select(mask, five, nine)\n  check(chosen[0] == 5)\n  for i in 1..{n} {{ check(chosen[i] == 9) }}\n  bits := simd.{prefix}_select(five, five, nine)\n  for i in 0..{n} {{ check(bits[i] == 13) }}')
    source.append('}')
source.append('}')
with tempfile.TemporaryDirectory(prefix='dyn-simd-lanes-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text('\n'.join(source))
    for mode in ('--debug', '--release'):
        command = [DYN, 'build', str(work), mode, '--no-cache', '--quiet', '--output', str(work / 'program')]
        if mode == '--release':
            command += ['--opt-level', '3', '--opt-remarks']
        built = subprocess.run(command, capture_output=True, text=True, timeout=300)
        assert built.returncode == 0, built.stderr
        subprocess.run([str(work / 'program')], check=True, timeout=30)
        if mode == '--release' and platform.machine().lower() in ('x86_64', 'amd64', 'aarch64', 'arm64'):
            assert 'vectorized' in built.stderr, built.stderr
    for target in ('aarch64-linux', 'riscv64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows', 'wasm32-wasi'):
        output = work / target
        subprocess.run([DYN, 'build', str(work), '--release', '--opt-level', '3', '--target', target, '--quiet', '--output', str(output)], check=True, timeout=300)
        emulator = {'aarch64-linux': 'qemu-aarch64', 'riscv64-linux': 'qemu-riscv64', 'x86_64-windows': 'wine'}.get(target)
        if emulator and shutil.which(emulator):
            subprocess.run([emulator, str(output)], check=True, timeout=60)
    # Short loads/stores must fail in debug and release before writing anything.
    for operation in ('load', 'store'):
        body = '_ = simd.u32x4_load(buffer[..])' if operation == 'load' else 'simd.u32x4_store(buffer[..], simd.u32x4_splat(1))'
        (work / 'main.dyn').write_text('use "std/simd" simd\nfn main() {\n buffer: [3]u32 = []\n '+body+'\n}')
        for mode in ('--debug', '--release'):
            subprocess.run([DYN, 'build', str(work), mode, '--quiet', '--output', str(work / 'program')], check=True, timeout=300)
            ran = subprocess.run([str(work / 'program')], capture_output=True, text=True, timeout=30)
            assert ran.returncode != 0 and 'short SIMD '+operation in ran.stderr, ran.stderr
print('PASS SIMD lanes: 10 lane types, arithmetic, masks, wrap, load/store bounds, native vectorization and cross-targets')
