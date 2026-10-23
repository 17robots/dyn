#!/usr/bin/env python3
"""Signed indexes and slice bounds: accepted like C, still bounds checked."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
RUNNERS = {'x86_64-linux': [], 'aarch64-linux': ['qemu-aarch64'], 'riscv64-linux': ['qemu-riscv64']}
WASI = ("const {WASI}=require('node:wasi'),fs=require('fs');(async()=>{const wasi=new WASI("
        "{version:'preview1',args:['test'],returnOnExit:true});const {instance}=await "
        "WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:"
        "wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});")
ran = []
with tempfile.TemporaryDirectory(prefix='dyn-signed-index-') as temporary:
    work = Path(temporary)
    for target, runner in RUNNERS.items():
        if runner and not shutil.which(runner[0]):
            continue
        for release in (False, True):
            program = work / f'{target}-{release}'
            subprocess.run([DYN, 'build', str(ROOT / 'tests/signed-index'), '--target', target, '--quiet',
                            '--no-cache', '--output', str(program)] + (['--release'] if release else []),
                           check=True, timeout=120)
            result = subprocess.run([*runner, str(program)], input='', capture_output=True, text=True, timeout=30)
            assert result.returncode == 101 and result.stdout == 'ok\n', (target, result)
            assert 'runtime check failed (index.ok) in pick' in result.stderr, result.stderr
            ran.append(target)
    if shutil.which('node'):
        program = work / 'test.wasm'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/signed-index'), '--target', 'wasm32-wasi', '--quiet',
                        '--no-cache', '--output', str(program)], check=True, timeout=120)
        result = subprocess.run(['node', '--no-warnings', '-e', WASI, str(program)],
                                input='', capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and result.stdout == 'ok\n', result
        ran.append('wasm32-wasi')
    # A signed type wider than usize cannot index on a 32-bit target.
    (work / 'wide').mkdir()
    (work / 'wide/main.dyn').write_text('fn main() {\n  values: [2]u8 = [1, 2]\n  i: i64 = 1\n  _ = values[i]\n}\n')
    wide = subprocess.run([DYN, 'check', str(work / 'wide'), '--target', 'wasm32-wasi'],
                          capture_output=True, text=True, timeout=60)
    assert wide.returncode != 0 and 'array index type is wider than usize on this target' in wide.stderr, wide
    native = subprocess.run([DYN, 'check', str(work / 'wide')], capture_output=True, text=True, timeout=60)
    assert native.returncode == 0, native
print('PASS signed indexes and slice bounds, negative index panics (debug/release): ' + ', '.join(dict.fromkeys(ran)))
