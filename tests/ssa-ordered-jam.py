#!/usr/bin/env python3
"""Ordered outer carries jam without changing floating or memory dependencies."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())


def program(width, shape):
    t, u = f'f{width}', f'u{width}'
    large = '10000000000000000.0' if width == 64 else '16777216.0'
    initial = '-0.0' if shape == 'special' else '0.0'
    bound = 7 if shape == 'odd' else 8
    expression = 'b[k * 8 + j]'
    if shape == 'alias':
        expression = 'c[k + j]'
    if shape == 'inner-carry':
        expression += ' + total'
    tail = 'c[j] = sum\n    total += c[j]'
    if width == 32:
        # F32 store forwarding remains conservative; exercise jam independently.
        tail = 'c[j] = sum\n    total += sum'
    if shape == 'cross':
        tail += '\n    other += total\n    total += other'
    if shape == 'branch':
        tail = 'if j % 2 == 0 { c[j] = sum } else { c[j] = -sum }\n    total += c[j]'
    init = f'for j in 0..8 {{ b[j] = 1.0 }}\n  b[0] = {large}\n  b[2] = -{large}\n  b[4] = {large}\n  b[6] = -{large}'
    if shape == 'special':
        # One quiet NaN payload and negative zero; compare every output bit.
        nan = 9221120237041090626 if width == 64 else 2143289410
        zero = 9223372036854775808 if width == 64 else 2147483648
        init = f'zero: {u} = {zero}\n  nan: {u} = {nan}\n  for z in 0..32 {{ b[z] = #bitcast({t}, zero) }}\n  b[3] = #bitcast({t}, nan)'
    return f'''use "std/io"
b: [32]{t}
c: [32]{t}
totals: [2]{t}
fn main() {{
  {init}
  for j in 0..32 {{ c[j] = #cast({t}, j) * 0.25 }}
  total: {t} = {initial}
  other: {t} = 0.0
  for j in 0..{bound} {{
    sum: {t} = {initial}
    for k in 0..4 {{ sum += {expression} }}
    {tail}
  }}
  totals[0] = total
  totals[1] = other
  _ = io.println(io.stdout(), "{{}} {{}}", #bitcast({u}, totals[0]), #bitcast({u}, totals[1]))
  for j in 0..{bound} {{ _ = io.println(io.stdout(), "{{}}", #bitcast({u}, c[j])) }}
}}
'''


def main():
    targets = [('x86_64-linux', [])]
    for target, emulator in [('aarch64-linux', 'qemu-aarch64'), ('riscv64-linux', 'qemu-riscv64')]:
        if shutil.which(emulator):
            targets.append((target, [emulator]))
    with tempfile.TemporaryDirectory(prefix='dyn-ordered-jam-') as temporary:
        work = Path(temporary)
        for target, runner in targets:
            for width in (32, 64):
                for shape in ('ordered', 'cross', 'special', 'alias', 'branch', 'odd', 'inner-carry'):
                    (work/'main.dyn').write_text(program(width, shape))
                    outputs = []
                    for mode in ('ssa', 'tree'):
                        env = dict(os.environ, DYN_SDK=str(ROOT))
                        env.pop('DYN_NO_SSA', None)
                        if mode == 'tree':
                            env['DYN_NO_SSA'] = '1'
                        binary = work/'test'
                        build = subprocess.run([DYN, 'build', str(work), '--release', '--opt-level', '3',
                            '--no-cache', '--quiet', '--opt-remarks', '--target', target,
                            '--output', str(binary)], env=env, capture_output=True, text=True, timeout=120)
                        assert build.returncode == 0, (target, width, shape, mode, build.stderr)
                        if mode == 'ssa':
                            assert re.search(r'remark: (?:kernel|main): SSA code generation,', build.stderr), build.stderr
                            jammed = 'unrolled and jammed' in build.stderr
                            eligible = shape in ('ordered', 'cross', 'special')
                            # Target range proof may conservatively retain checks.
                            assert not jammed or eligible, (target, width, shape, build.stderr)
                            if target in ('x86_64-linux', 'aarch64-linux'):
                                assert jammed == eligible, (target, width, shape, build.stderr)
                        result = subprocess.run([*runner, str(binary)], capture_output=True, text=True, timeout=15)
                        assert result.returncode == 0, (target, width, shape, mode, result)
                        outputs.append(result.stdout)
                    assert outputs[0] == outputs[1], (target, width, shape, outputs)
                    if shape == 'ordered':
                        one = 1065353216 if width == 32 else 4607182418800017408
                        assert outputs[0].splitlines()[0] == f'{one} 0', outputs
                    if shape == 'special':
                        negative_zero = 2147483648 if width == 32 else 9223372036854775808
                        assert outputs[0].splitlines()[1] == str(negative_zero), outputs
            print(f'PASS ordered jam {target}: F32/F64 ordered, cross carries, special bits and rejection cases', flush=True)


if __name__ == '__main__':
    main()
