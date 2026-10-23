#!/usr/bin/env python3
"""Pointer casts truncate at target width; forged addresses are never accessed.

DYN_QEMU_ARM / DYN_QEMU_RISCV32 accept command wrappers (as in bare-ssa.py).
Run with DYN pointing to an unfixed compiler for a failing negative baseline.
"""
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
POINTERS = {'raw': 'rawptr', 'typed': '*u8', 'function': 'fn(i32) i32'}
INPUTS = {'u64': (0x12345678fedcba98, 64), 'i64': (-81985529216486896, 64),
          'u32': (0xfedcba98, 32), 'i32': (-2, 32), 'i8': (-2, 8)}


def source(bits):
    declarations = ['use "std/io"']
    checks = []
    names = []
    for kind, pointer in POINTERS.items():
        declarations.append(f'fn identity_{kind}(p:{pointer}) {pointer} {{ return p }}')
        for integer, (value, width) in INPUTS.items():
            name = f'cast_{kind}_{integer}'
            names.append(name)
            declarations.append(f'pub fn {name}(x:{integer}) u64 {{ '
                                f'return #cast(u64,identity_{kind}(#cast({pointer},x))) }}')
            expected = value & ((1 << min(bits, width)) - 1)
            checks.append(f'if {name}({value})!={expected} '
                          f'{{ #panic("{name}") }}')
    # Reinterpret through all legal pointer categories without calling/dereferencing.
    declarations.append('pub fn pointer_chain(x:u64) u64 { '
                        'return #cast(u64,#cast(fn(i32) i32,#cast(*u8,#cast(rawptr,x)))) }')
    names.append('pointer_chain')
    expected = 0x12345678fedcba98 & ((1 << bits) - 1)
    checks.append(f'if pointer_chain(0x12345678fedcba98)!={expected} {{ #panic("pointer_chain") }}')
    return '\n'.join(declarations + ['fn main() {'] + checks +
                     ['_=io.write_all(io.stdout(),"POINTER WIDTH PASS\\n")', '}']), names


def run(command):
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise AssertionError(f'guest exceeded 30 seconds: {command}')
    assert process.returncode == 0, (command, process.returncode, stdout, stderr)
    assert stdout.replace(b'\r\n', b'\n') == b'POINTER WIDTH PASS\n', (command, stdout, stderr)


def main():
    targets = [(None, [], 64)]
    for architecture, variable, program, board in (
        ('riscv32', 'DYN_QEMU_RISCV32', 'qemu-system-riscv32', ['-machine', 'virt', '-bios', 'none']),
        ('thumbv7em', 'DYN_QEMU_ARM', 'qemu-system-arm',
         ['-machine', 'mps2-an500', '-semihosting-config', 'enable=on,target=native']),
    ):
        qemu = shlex.split(os.environ.get(variable, '')) or [program]
        if not shutil.which(qemu[0]):
            print(f'SKIP {architecture}: set {variable} (missing {qemu[0]})', flush=True)
            continue
        for suffix in ('none', 'none-soft'):
            targets.append((f'{architecture}-{suffix}', [*qemu, *board, '-nographic', '-kernel'], 32))
    with tempfile.TemporaryDirectory(prefix='dyn-pointer-width-') as temporary:
        work = Path(temporary)
        for target, runner, bits in targets:
            program, names = source(bits)
            (work / 'main.dyn').write_text(program)
            for mode in ('ssa', 'tree'):
                env = dict(os.environ)
                env.pop('DYN_NO_SSA', None)
                if mode == 'tree':
                    env['DYN_NO_SSA'] = '1'
                image = work / 'program'
                command = [DYN, 'build', str(work), '--release', '--no-cache', '--opt-remarks',
                           '--output', str(image)]
                if target:
                    command += ['--target', target]
                built = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120)
                log = built.stdout + built.stderr
                assert built.returncode == 0, (target, mode, log)
                if mode == 'tree':

                    assert 'SSA code generation' not in log, log
                else:
                    for name in names:
                        assert re.search(rf'^remark: {name}: SSA code generation,', log, re.MULTILINE), (name, log)
                run([*runner, str(image)])
                print(f'PASS {target or "host64"} {mode}: {", ".join(names)}', flush=True)


if __name__ == '__main__':
    main()
