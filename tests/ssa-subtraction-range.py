#!/usr/bin/env python3
"""Subtraction intervals remove proven checks and preserve observable failures."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
FUNCS = 'use "std/io"\nflags: [64]u8\npub fn safe(round:usize) usize {\n  if round >= 4 { return 0 }\n  limit := #len(flags) - round * 3\n  for i in 2..limit {\n    flags[i] = 1\n    j := i * 2\n    for j < limit { flags[j] = 0\n    j += i }\n  }\n  return limit\n}\npub fn unsigned(a:u64,b:u64) u64 { return a-b }\npub fn signed(a:i64,b:i64) i64 { return a-b }\npub fn narrow(a:i8,b:i8) i8 { return a-b }\npub fn wrapped(a:u64,b:u64) u64 { return #wrap(a-b) }\npub fn read(a:u64,b:u64) u8 { return flags[a-b] }\npub fn read_wrap(a:u64,b:u64) u8 { return flags[#wrap(a-b)] }\npub fn dynamic(n:usize) { for i in 0..n { flags[i] = 1 } }\npub fn cleanup(a:u64,b:u64) u64 {\n  defer { _=io.write_all(io.stdout(),"CLEAN\\n") }\n  return a-b\n}\npub fn left() u64 { _=io.write_all(io.stdout(),"LEFT\\n")\nreturn 0 }\npub fn right() u64 { _=io.write_all(io.stdout(),"RIGHT\\n")\nreturn 1 }\n'
CASES = [
    ('safe', '''for r in 0..4 {
if safe(r)!=64-r*3 { #panic("limit") }
if flags[2]!=1 || flags[64-r*3-1]!=1 { #panic("store") }
}''', '', ''),
    ('edges', '''if unsigned(18446744073709551615,1)!=18446744073709551614 { #panic("u64") }
if signed(-1,9223372036854775807)!=-9223372036854775808 { #panic("i64") }
if narrow(-120,7)!=-127 { #panic("i8") }
if wrapped(0,1)!=18446744073709551615 { #panic("wrap") }
dynamic(#cast(usize,unsigned(7,7)))''', '', ''),
    ('underflow', '_=unsigned(0,1)', 'overflow', ''),
    ('signed-overflow', '_=signed(-9223372036854775808,1)', 'overflow', ''),
    ('signed-upper-overflow', '_=signed(9223372036854775807,-1)', 'overflow', ''),
    ('narrow-overflow', '_=narrow(-128,1)', 'overflow', ''),
    ('index-underflow', '_=read(0,1)', 'overflow', ''),
    ('index-too-large', '_=read(65,1)', 'index.ok', ''),
    ('wrap-bounds', '_=read_wrap(0,1)', 'index.ok', ''),
    ('dynamic-bounds', 'dynamic(65)', 'index.ok', ''),
    ('cleanup', '_=cleanup(0,1)', 'overflow', 'CLEAN\n'),
    ('order', '_=unsigned(left(),right())', 'overflow', 'LEFT\nRIGHT\n'),
]

def main():
    targets = [('x86_64-linux', [])]
    for target, emulator in [('aarch64-linux', 'qemu-aarch64'), ('riscv64-linux', 'qemu-riscv64')]:
        if shutil.which(emulator):
            targets.append((target, [emulator]))
    with tempfile.TemporaryDirectory(prefix='dyn-subtraction-range-') as temporary:
        work = Path(temporary)
        for target, runner in targets:
            for mode in ('ssa', 'tree'):
                env = dict(os.environ, DYN_SDK=str(ROOT))
                env.pop('DYN_NO_SSA', None)
                if mode == 'tree':
                    env['DYN_NO_SSA'] = '1'
                for name, body, panic, prefix in CASES:
                    (work/'main.dyn').write_text(FUNCS+'\nfn main() {\n'+body+'\n_=io.write_all(io.stdout(),"OK\\n") }\n')
                    binary = work/'test'
                    build = subprocess.run([DYN, 'build', str(work), '--release', '--opt-level', '3',
                        '--no-cache', '--quiet', '--opt-remarks', '--target', target,
                        '--output', str(binary)], env=env, capture_output=True, text=True, timeout=120)
                    assert build.returncode == 0, (target, mode, name, build.stderr)
                    if mode == 'ssa':
                        function = 'main'
                        assert re.search(r'remark: '+function+r': SSA code generation,', build.stderr), build.stderr
                    else:
                        assert 'SSA code generation' not in build.stderr, build.stderr
                    result = subprocess.run([*runner, str(binary)], capture_output=True, text=True, timeout=15)
                    assert result.stdout == prefix + ('' if panic else 'OK\n'), (target, mode, name, result)
                    if panic:
                        assert result.returncode != 0 and panic in result.stderr.lower(), (target, mode, name, result)
                    else:
                        assert result.returncode == 0, (target, mode, name, result)
                    if target == 'x86_64-linux' and mode == 'ssa' and name == 'safe':
                        # Nested calls may now inline safe into main. Inspect the public
                        # function in a separate shared build so code-shape proof remains.
                        (work/'main.dyn').write_text(FUNCS)
                        shared = work/'proof.so'
                        proof = subprocess.run([DYN, 'build', str(work), '--shared', '--release',
                            '--opt-level', '3', '--no-cache', '--quiet', '--opt-remarks',
                            '--target', target, '--output', str(shared)], env=env,
                            capture_output=True, text=True, timeout=120)
                        assert proof.returncode == 0, proof.stderr
                        assert re.search(r'remark: safe: SSA code generation,', proof.stderr), proof.stderr
                        dis = subprocess.run(['objdump', '-d', '-Mintel', str(shared)], capture_output=True,
                                             text=True, check=True, timeout=15).stdout
                        functions = re.split(r'\n(?=[0-9a-f]+ <)', dis)
                        safe = [f for f in functions if re.match(r'[0-9a-f]+ <(?:[^>]*_)?safe>:', f)]
                        assert len(safe) == 1, 'missing public safe function'
                        assert 'dyn_check_failed' not in safe[0], safe[0]
                print(f'PASS subtraction range {target} {mode}: {len(CASES)} cases', flush=True)

if __name__ == '__main__':
    main()
