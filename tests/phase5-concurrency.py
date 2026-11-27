#!/usr/bin/env python3
"""Phase 5: sync.Channel<T>, thread.Scope, typed pool.submit<C>, std/mem/heap
and std/fiber (switching, nesting, isolation) in debug and release, natively
and under qemu-user for AArch64 and RISC-V when it is installed."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
PROGRAMS = {
    'phase5-concurrency': 'phase5 ok',
    'phase5-heap': 'heap ok',
    'phase5-fiber': 'fiber ok',
}
EMULATORS = {'aarch64-linux': 'qemu-aarch64', 'riscv64-linux': 'qemu-riscv64'}

env = dict(os.environ, DYN_SDK=str(ROOT))
with tempfile.TemporaryDirectory(prefix='dyn-phase5-') as scratch:
    for name, expected in PROGRAMS.items():
        targets = [('x86_64-linux', None)]
        for target, emulator in EMULATORS.items():
            if shutil.which(emulator):
                targets.append((target, emulator))
            else:
                print(f'SKIP {name} {target}: missing {emulator}', flush=True)
        for target, emulator in targets:
            for mode in ('debug', 'release'):
                output = Path(scratch) / f'{name}-{target}-{mode}'
                command = [DYN, 'build', str(ROOT / 'tests' / name), '--target', target, '--output', str(output), '--no-cache']
                if mode == 'release':
                    command.append('--release')
                built = subprocess.run(command, capture_output=True, text=True, env=env, timeout=300)
                assert built.returncode == 0, f'{name} {target} {mode} build:\n{built.stderr}'
                run = [emulator, str(output)] if emulator else [str(output)]
                # Thread scheduling varies; run each binary a few times.
                for _ in range(3):
                    ran = subprocess.run(run, capture_output=True, text=True, timeout=120)
                    assert ran.returncode == 0 and expected in ran.stdout, (
                        f'{name} {target} {mode}: rc={ran.returncode}\n{ran.stdout}\n{ran.stderr}')
    # Programs that do not use std/fiber link none of it.
    hello = Path(scratch) / 'hello'
    hello.mkdir()
    (hello / 'main.dyn').write_text('use io "std/io"\nfn main() {\n  io.println("hi")\n}\n')
    binary = Path(scratch) / 'hello-bin'
    built = subprocess.run([DYN, 'build', str(hello), '--release', '--output', str(binary), '--no-cache'],
                           capture_output=True, text=True, env=env, timeout=120)
    assert built.returncode == 0, built.stderr
    assert b'dyn_fiber_switch' not in binary.read_bytes(), 'unused fiber runtime was linked'
print('PASS phase 5 concurrency: channels, scopes, typed pool, heap, fibers (switch, nesting, isolation)')
