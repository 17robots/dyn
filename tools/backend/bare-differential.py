#!/usr/bin/env python3
"""Differential check of a bare-metal target against x86-64 Linux output.

Uses the value corpus of native-differential.py without the C interop part.
The bare-metal image has no command line, so QEMU's generic loader writes the
case index into RAM at INDEX_ADDRESS before the program starts. Console
output on the board merges stdout and stderr, so the reference compares
stdout followed by stderr.

Set DYN_QEMU_RISCV32 (DYN_QEMU_RISCV64, DYN_QEMU_ARM) to a command that runs
the board's QEMU, for example "podman run --rm -i --init -v $TMPDIR:$TMPDIR
dyn-qemu"; the cases then run inside that one container. Without it the QEMU
from PATH runs.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('native_differential', HERE/'native-differential.py')
differential = importlib.util.module_from_spec(spec)
spec.loader.exec_module(differential)

# Per target: QEMU program, board options, the address that receives the case
# index (just past the arenas), and the wrapper variable.
VIRT = '-machine virt -bios none'
BOARDS = {
    'riscv32-none': ('qemu-system-riscv32', VIRT, 0x87F00000, 'DYN_QEMU_RISCV32'),
    'riscv64-none': ('qemu-system-riscv64', VIRT, 0x87F00000, 'DYN_QEMU_RISCV64'),
    'thumbv7em-none': ('qemu-system-arm', '-machine mps2-an500 -semihosting-config enable=on,target=native',
                       0x202F0000, 'DYN_QEMU_ARM')}


def bare_program(program, address):
    """Replaces the command-line main with one that reads the index from RAM."""
    start = program.index('fn main() {')
    head = program[:start].replace('use "std/process"\n', '').replace('use "std/strings"\n', '')
    tail = program[start:]
    body = tail[tail.index('  case index / 128 {'):]
    return (head.replace('use "std/io"\n', 'use "std/io"\nuse "std/mmio"\n') +
            'fn main() {\n' f'  index := #cast(u64, mmio.load_u32({address:#x}))\n' + body)


def build(compiler, root, program, target, release):
    outputs = {}
    for name, which, source in (('bare', target, bare_program(program, BOARDS[target][2])), ('reference', 'x86_64-linux', program)):
        (root/name).mkdir(exist_ok=True)
        (root/name/'main.dyn').write_text(source)
        output = root/(name + '-image')
        built = subprocess.run([str(compiler), 'build', str(root/name), '--target', which, '--no-cache', '--quiet',
                                '--output', str(output)] + (['--release'] if release else []), capture_output=True, text=True, timeout=900)
        if built.returncode:
            sys.exit(f'{name} build failed:\n{built.stderr[-4000:]}')
        outputs[name] = output
    return outputs


def run_bare(target, image, count, jobs, directory):
    """Boots the image once per case inside one shell, in parallel."""
    qemu, board, address, variable = BOARDS[target]
    script = directory/'run-cases.sh'
    script.write_text(
        '#!/bin/sh\n'
        f'i=$1; timeout -s KILL 20 {qemu} {board} -nographic -kernel {image} '
        f'-device loader,addr={address:#x},data=$i,data-len=4 > {directory}/case-$i.out 2>/dev/null\n'
        f'echo $? > {directory}/case-$i.status\n')
    script.chmod(0o755)
    wrapper = shlex.split(os.environ.get(variable, ''))
    loop = (f'i=0; while [ $i -lt {count} ]; do {script} $i & i=$((i+1)); '
            f'if [ $((i % {jobs})) -eq 0 ]; then wait; fi; done; wait')
    command = [*wrapper, 'sh', '-c', loop]
    subprocess.run(command, timeout=7200, check=True)
    results = []
    for i in range(count):
        status_file, output_file = directory/f'case-{i}.status', directory/f'case-{i}.out'
        if not status_file.exists() or not output_file.exists():
            raise RuntimeError(f'{target} runner did not produce case {i} results')
        status = int(status_file.read_text())
        if status == 137: status = 'timeout'
        output = output_file.read_bytes().replace(b'\r\n', b'\n') if output_file.exists() else b''
        results.append((status, output))
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', choices=sorted(BOARDS), default='riscv32-none')
    parser.add_argument('--compiler', type=Path, default=ROOT/'build/dyn')
    parser.add_argument('--per-function', type=int, default=8)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--jobs', type=int, default=os.cpu_count() or 4)
    parser.add_argument('--first', type=int, default=0, help='first case to compare')
    parser.add_argument('--release', action='store_true', help='build both programs optimized')
    parser.add_argument('--limit', type=int, default=0, help='compare at most this many cases')
    args = parser.parse_args()
    if differential.runner('x86_64-linux') is None:
        print('SKIP bare differential: the reference needs an x86-64 Linux host'); return
    program_name, _, address, variable = BOARDS[args.target]
    if not os.environ.get(variable) and not shutil.which(program_name):
        print(f'SKIP {args.target} differential: {program_name} not found'); return
    rng = random.Random(args.seed)
    # Both programs must mean the same: pointer-sized integers become 64-bit.
    def pointer_free(text):
        return re.sub(r'\busize\b', 'u64', re.sub(r'\bisize\b', 'i64', text))
    source = pointer_free(differential.corpus())
    differential.EXTRA = pointer_free(differential.EXTRA)
    differential.INTEROP = ''
    original = differential.corpus
    differential.corpus = lambda: source
    program, count = differential.build_program(rng, args.per_function)
    differential.corpus = original
    with tempfile.TemporaryDirectory(prefix='dyn-bare-diff-') as directory:
        root = Path(directory)
        outputs = build(args.compiler, root, program, args.target, args.release)
        last = count if not args.limit else min(count, args.first + args.limit)
        expected = differential.run_cases([], outputs['reference'], count, directory, args.jobs)
        bare = run_bare(args.target, outputs['bare'], count, args.jobs, root)
        failures = []
        slow = crashes = faults = 0
        for i in range(args.first, last):
            # Long loops end sooner natively than under QEMU; either side timing out is inconclusive.
            if 'timeout' in (expected[i][0], bare[i][0]):
                slow += 1
                continue
            status, out, err = expected[i]
            # Stack traces name each program's own source lines; compare the rest.
            want = (status, re.sub(rb'stack trace:\n(  at [^\n]*\n)*', b'', out + err))
            got = (bare[i][0], re.sub(rb'stack trace:\n(  at [^\n]*\n)*', b'', bare[i][1]))
            # Signals and board traps agree only on the fault class, not its cause.
            if want[0] == 'crash' and got[0] in (102, 103):
                faults += 1
                continue
            # Address maps differ: a Linux crash alone cannot establish what
            # happened on Cortex-M. Report it as inconclusive, not a match or
            # proof of a low-address read.
            if want[0] == 'crash' and args.target == 'thumbv7em-none':
                crashes += 1
                continue
            if want != got:
                failures.append(i)
        for i in failures[:25]:
            print(f'MISMATCH case {i}: {args.target}={bare[i]} reference={(expected[i][0], expected[i][1] + expected[i][2])}')
        if failures:
            (Path(tempfile.gettempdir())/'dyn-bare-diff-main.dyn').write_text(bare_program(program, address))
            sys.exit(f'{len(failures)} of {last - args.first} {args.target} cases differ '
                     f'(program saved to {tempfile.gettempdir()}/dyn-bare-diff-main.dyn)')
        compared = last - args.first
        matched = compared - slow - crashes - faults
        print(f'PASS {args.target}{" release" if args.release else " debug"} differential: '
              f'{compared} cases, {matched} exact outcomes, {faults} fault-class agreements, '
              f'{slow} timeout cases inconclusive, {crashes} reference-crash cases inconclusive')



if __name__ == '__main__':
    main()
