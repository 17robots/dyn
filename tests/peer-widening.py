#!/usr/bin/env python3
"""Binary operators widen the narrower number operand when the widening is
lossless on every target, in debug and release and on every Linux backend.
u64 against i64 still needs a cast."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
EXPECTED = ('4000000005 4000000200 20000000000\nfalse true true\n4000000007 100\n205 4000000005\n'
            '1983905797\n4000000005 -203 4000000001 400 4000000010\n')
WASI = r'''
const {WASI}=require('node:wasi'),fs=require('fs');
(async()=>{const wasi=new WASI({version:'preview1',args:['test'],returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});
'''
with tempfile.TemporaryDirectory(prefix='dyn-peer-widening-') as temporary:
    for name, flags, emulator in (('debug', ['--debug', '--no-check-overflow'], []), ('release', ['--release'], []),
                                  ('arm', ['--target', 'aarch64-linux', '--release'], ['qemu-aarch64']),
                                  ('arm-debug', ['--target', 'aarch64-linux', '--no-check-overflow'], ['qemu-aarch64']),
                                  ('riscv', ['--target', 'riscv64-linux', '--release'], ['qemu-riscv64']),
                                  ('windows.exe', ['--target', 'x86_64-windows', '--release'], ['wine']),
                                  ('wasi.wasm', ['--target', 'wasm32-wasi', '--no-check-overflow'], ['node', '--no-warnings', '-e', WASI]),
                                  ('wasi-release.wasm', ['--target', 'wasm32-wasi', '--release'],
                                   ['node', '--no-warnings', '-e', WASI])):
        program = Path(temporary) / name
        built = subprocess.run([DYN, 'build', str(ROOT / 'tests/peer-widening'), *flags, '--no-cache',
                                '--output', str(program)], capture_output=True, text=True, timeout=120)
        assert built.returncode == 0, (name, built.stderr)
        if emulator and not shutil.which(emulator[0]):
            continue
        result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=120,
                                env={**os.environ, 'WINEDEBUG': '-all'})
        assert result.returncode == 0 and result.stdout.replace('\r\n', '\n') == EXPECTED, (name, result)
    project = Path(temporary) / 'bad'
    project.mkdir()
    (project / 'main.dyn').write_text('fn main() {\n  a: u64 = 1\n  b: i64 = 2\n  _ = a < b\n}\n')
    bad = subprocess.run([DYN, 'check', str(project)], capture_output=True, text=True, timeout=60)
    assert bad.returncode != 0 and 'mismatched types u64 and i64' in bad.stderr, bad
print('PASS peer widening of mixed number operands')
