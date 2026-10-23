#!/usr/bin/env python3
"""Qualify real register allocation and SIMD lowering against scalar O2."""
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
def run(*args):
    p = subprocess.run(list(map(str, args)), cwd=ROOT, text=True, capture_output=True, timeout=90)
    assert p.returncode == 0, (args, p.returncode, p.stdout, p.stderr)
    return p

source = '''
fn touch(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64) i64 {
  return a + b * 2 + c * 3 + d * 4 + e * 5 + f * 6
}
fn pressure(seed: i64) i64 {
  a := seed + 1 b := seed + 2 c := seed + 3 d := seed + 4
  e := seed + 5 f := seed + 6 g := seed + 7 h := seed + 8
  total: i64 = 0
  callback := &touch
  for i in 0..30 {
    called := callback(a, b, c, d, e, f)
    if i % 2 == 0 { total += called + g * 7 + h * 8 }
    else { total += a + b * 2 + c * 3 + d * 4 + e * 5 + f * 6 + g * 7 + h * 8 }
  }
  escaped := seed
  pointer := &escaped
  pointer.* += 10
  return total + escaped
}
'''
# Small aggregate copies must retain memmove semantics at every byte
# alignment, including overlapping source/destination and exact self-copy.
copy_kernels = []
for size in (1, 2, 3, 4, 7, 8, 9, 15, 16, 17, 31, 32, 33, 40, 63, 64, 65, 129):
    shifts = sorted(set((0, -1, 1, -3, 3, -7, 7, -size, size, -size-1, size+1)))
    name = f'copy_case_{size}'
    source += f'''
struct CopyBlock{size} {{ bytes: [{size}]u8 }}
fn {name}(shift: i64) {{
  storage: [520]u8 = []
  for i in 0..520 {{ storage[i] = #cast(u8, (i % 251)) }}
  origin: usize = 193
  destination := #cast(usize, (#cast(i64, origin) + shift))
  from := #cast(*CopyBlock{size}, &storage[origin])
  to := #cast(*CopyBlock{size}, &storage[destination])
  to.* = from.*
  for i in 0..520 {{
    expected := i
    if i >= destination && i < destination + {size} {{ expected = origin + i - destination }}
    if storage[i] != #cast(u8, (expected % 251)) {{ #panic("overlapping small aggregate copy") }}
  }}
}}
'''
    copy_kernels.extend(f'{name}({shift})' for shift in shifts)
kernels = []
for t in ('u32', 'i32', 'u64', 'i64'):
    for op, name in (('+', 'add'), ('-', 'sub'), ('&', 'and'), ('|', 'or'), ('^', 'xor')):
        for n in (3, 19):
            function = f'vector_{t}_{name}_{n}'
            kernels.append(function)
            operation = f'#wrap(a[i] {op} b[i])' if op in ('+', '-') else f'a[i] {op} b[i]'
            source += f'''
fn {function}() {{
  a: [{n}]{t} = [] b: [{n}]{t} = [] c: [{n}]{t} = []
  for i in 0..{n} {{ a[i] = #cast({t}, i) b[i] = #cast({t}, -1) }}
  for i in 0..{n} {{ c[i] = {operation} }}
  for i in 0..{n} {{ if c[i] != {operation} {{ #panic("SIMD scalar oracle") }} }}
  // Same-array destinations are safe because every lane uses the same index.
  for i in 0..{n} {{ a[i] = {operation} }}
  for i in 0..{n} {{ if a[i] != c[i] {{ #panic("SIMD same-array alias") }} }}
}}
'''
source += '''fn main() {
  for seed in 0..20 {
    signed_seed := #cast(i64, seed)
    result := pressure(signed_seed)
    if result != 30 * (36 * signed_seed + 204) + signed_seed + 10 { #panic("register pressure/calls/escape") }
  }
'''
source += '\n'.join(f'  {name}()' for name in kernels) + '\n'
source += '\n'.join(f'  {call}' for call in copy_kernels) + '\n}\n'
with tempfile.TemporaryDirectory(prefix='dyn-machine-opt-') as directory:
    work = Path(directory)
    module = work/'src'
    module.mkdir()
    (module/'main.dyn').write_text(source)
    for level in (2, 3):
        output = work/f'o{level}'
        p = run(DYN, 'build', module, '--release', '--opt-level', level,
                '--opt-remarks', '--emit-object', '--output', output)
        run(output)
        if level == 2 and platform.machine().lower() in ('x86_64', 'amd64') and shutil.which('objdump'):
            listing = run('objdump', '-d', '--disassemble=copy_case_40', output.with_suffix('.o')).stdout
            assert '<copy_case_40>:' in listing, listing
            assert not re.search(r'\bstd\b|\brep(?:z)? movsb\b', listing), 'small copies regressed to direction-flag byte strings'
        if level == 3:
            optimized_isa = platform.machine().lower() in ('x86_64', 'amd64', 'aarch64', 'arm64')
            if optimized_isa:
                assert len(re.findall(r'vectorized 19 integer elements', p.stderr)) >= 20, p.stderr
            else:
                assert 'vectorized' not in p.stderr, p.stderr
            # x86-64 System V and AArch64 functions take the SSA path and
            # its register allocator.
            if optimized_isa and platform.system() != 'Windows':
                assert 'SSA code generation' in p.stderr, p.stderr
            else:
                assert 'integer locals allocated to callee-saved registers' not in p.stderr, p.stderr
            data = output.with_suffix('.o').read_bytes()
            if platform.machine().lower() in ('x86_64', 'amd64'):
                assert re.search(rb'\x66[\x40-\x4f]?\x0f\xfe[\xc0-\xff]', data), 'missing SSE2 paddd'
                assert re.search(rb'\x66[\x40-\x4f]?\x0f\xd4[\xc0-\xff]', data), 'missing SSE2 paddq'
            elif platform.machine().lower() in ('aarch64', 'arm64'):
                # Any registers: 0x4ea08400 | m << 16 | n << 5 | d, little endian.
                words = [int.from_bytes(data[i:i + 4], 'little') for i in range(0, len(data) - 3, 4)]
                assert any(w & 0xffe0fc00 == 0x4ea08400 for w in words), 'missing NEON add .4s'
                assert any(w & 0xffe0fc00 == 0x4ee08400 for w in words), 'missing NEON add .2d'
    # Cross-host execution proves the AArch64 encodings and callee saves too.
    if platform.system() == 'Linux' and platform.machine().lower() in ('x86_64', 'amd64') and shutil.which('qemu-aarch64'):
        output = work/'arm64'
        run(DYN, 'build', module, '--release', '--opt-level', 3, '--target', 'aarch64-linux', '--output', output)
        run('qemu-aarch64', output)
    # RV64 currently has scalar lowering only. Matching vector kernels must
    # remain valid RV64 code at O3, never fall through to x86 instruction bytes.
    if shutil.which('qemu-riscv64'):
        output = work/'riscv64'
        p = run(DYN, 'build', module, '--release', '--opt-level', 3,
                '--opt-remarks', '--target', 'riscv64-linux', '--output', output)
        assert 'vectorized' not in p.stderr, p.stderr
        run('qemu-riscv64', output)
        print('PASS RV64 O3 matching SIMD kernels execute scalar lowering under QEMU')
    # Debug locations retain stack homes; checked arithmetic cannot use the
    # wrapping vector path, even when every other loop condition matches.
    debug = work/'debug'
    p = run(DYN, 'build', module, '--release', '--opt-level', 3, '--debug-info',
            '--opt-remarks', '--output', debug)
    run(debug)
    assert 'allocated to callee-saved registers' not in p.stderr, p.stderr
    assert 'vectorized' not in p.stderr, p.stderr
    (module/'main.dyn').write_text('''fn main() {
  a: [19]u32 = [] b: [19]u32 = [] c: [19]u32 = []
  for i in 0..19 { a[i] = 4294967295 b[i] = 1 }
  for i in 0..19 { c[i] = a[i] + b[i] }
}''')
    checked = work/'checked'
    p = run(DYN, 'build', module, '--release', '--opt-level', 3,
            '--opt-remarks', '--output', checked)
    assert 'vectorized' not in p.stderr, p.stderr
    failed = subprocess.run([str(checked)], capture_output=True)
    assert failed.returncode != 0, 'checked overflow disappeared'
print('PASS register pressure, calls, loop liveness, escapes, overlapping copies, SSE2/NEON arithmetic, aliases and scalar tails')
