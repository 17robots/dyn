#!/usr/bin/env python3
"""Enum payloads build, copy, alias and read on every runnable target, and keep their rules."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = str(ROOT / 'tests/tagged-enums')
WASI = ("const {WASI}=require('node:wasi'),fs=require('fs');(async()=>{const wasi=new WASI({version:'preview1',"
        "returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),"
        "{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})()"
        ".catch(e=>{console.error(e);process.exit(1)});")
RUNNERS = {None: [], 'aarch64-linux': ['qemu-aarch64'], 'riscv64-linux': ['qemu-riscv64'],
           'wasm32-wasi': ['node', '--no-warnings', '-e', WASI]}
REJECTED = {
    'first variant': ('enum E { A: i32, B }\nfn main() {\n}\n', 'first enum variant has no payload'),
    'explicit value': ('enum E { Null, A = 4 }\nfn main() {\n}\n', 'no explicit values'),
    'cast': ('enum E { Null, A: i32 }\nfn main() {\n  _ = #cast(E, 1)\n}\n', 'cast'),
    'equality': ('enum E { Null, A: i32 }\nfn f(e: E) bool {\n  return e == E.Null\n}\nfn main() {\n  _ = f(E.Null)\n}\n', ''),
}
with tempfile.TemporaryDirectory(prefix='dyn-tagged-') as temporary:
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
    for name, (text, expected) in REJECTED.items():
        directory = Path(temporary) / name.replace(' ', '-')
        directory.mkdir()
        (directory / 'main.dyn').write_text(text)
        result = subprocess.run([DYN, 'check', str(directory)], capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and expected in result.stderr, (name, result.stderr)
print('PASS enum payloads on every runnable target, and their rules')
