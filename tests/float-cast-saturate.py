#!/usr/bin/env python3
"""Float to integer casts saturate, with NaN giving zero, on every runnable target."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = str(ROOT / 'tests/float-cast-saturate')
WASI = ("const {WASI}=require('node:wasi'),fs=require('fs');(async()=>{const wasi=new WASI({version:'preview1',"
        "returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),"
        "{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})()"
        ".catch(e=>{console.error(e);process.exit(1)});")
RUNNERS = {
    None: [],
    'aarch64-linux': ['qemu-aarch64'],
    'riscv64-linux': ['qemu-riscv64'],
    'wasm32-wasi': ['node', '--no-warnings', '-e', WASI],
}
ran = []
with tempfile.TemporaryDirectory(prefix='dyn-float-cast-') as temporary:
    for target, runner in RUNNERS.items():
        if runner and not shutil.which(runner[0]):
            continue
        for mode in ('--debug', '--release'):
            program = Path(temporary) / f'program-{target}{mode}'
            command = [DYN, 'build', SOURCE, mode, '--quiet', '--no-cache', '--output', str(program)]
            if target:
                command += ['--target', target]
            subprocess.run(command, check=True, timeout=120)
            subprocess.run(runner + [str(program)], check=True, timeout=60)
            ran.append(f'{target or "host"} {mode[2:]}')
    for target in ('riscv32-none', 'riscv32-none-soft', 'thumbv7em-none', 'thumbv7em-none-soft', 'riscv64-none'):
        for mode in ('--debug', '--release'):
            output = str(Path(temporary) / f'{target}{mode}')
            subprocess.run([DYN, 'build', SOURCE, mode, '--quiet', '--no-cache', '--target', target,
                            '--output', output], check=True, timeout=120)
print('PASS float casts saturate:', ', '.join(ran))
