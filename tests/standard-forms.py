#!/usr/bin/env python3
"""for x, i and text cases run the same on every backend: x86-64 debug and
release, AArch64 and RISC-V under QEMU, and WASI under Node."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = ROOT / 'tests/standard-forms'
EXPECTED = (SOURCE / 'expected.txt').read_text()
WASI = ("const {WASI}=require('node:wasi'),fs=require('fs');(async()=>{const wasi=new WASI({version:'preview1',"
        "returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),"
        "{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})()"
        ".catch(e=>{console.error(e);process.exit(1)});")
ran = []
with tempfile.TemporaryDirectory(prefix='dyn-standard-forms-') as temporary:
    for name, flags, runner in (('debug', [], []), ('release', ['--release'], []),
                                ('arm', ['--target', 'aarch64-linux', '--release'], ['qemu-aarch64']),
                                ('arm-debug', ['--target', 'aarch64-linux'], ['qemu-aarch64']),
                                ('riscv', ['--target', 'riscv64-linux', '--release'], ['qemu-riscv64']),
                                ('wasi.wasm', ['--target', 'wasm32-wasi'], ['node', '--no-warnings', '-e', WASI]),
                                ('wasi-release.wasm', ['--target', 'wasm32-wasi', '--release'],
                                 ['node', '--no-warnings', '-e', WASI])):
        if runner and not shutil.which(runner[0]):
            continue
        output = Path(temporary) / name
        subprocess.run([DYN, 'build', str(SOURCE), *flags, '--no-cache', '--quiet', '--output', str(output)],
                       check=True, timeout=120)
        result = subprocess.run([*runner, str(output)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0 and result.stdout == EXPECTED, (name, result.stdout, result.stderr)
        ran.append(name)
print('PASS for x, i and text cases: ' + ', '.join(ran))
