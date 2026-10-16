#!/usr/bin/env python3
"""Qualify the independent compiler on Windows and macOS hosts."""
import os
import json
import tarfile
import tempfile
import zipfile
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get('BUILD', ROOT/'build')).resolve()
env = dict(os.environ, DYN_WITH_LLVM='0', LLVM_CONFIG='false', CXX='false',
           DYN_SDK=str(ROOT), DYN_ASSEMBLY_ORACLE='0', DYN_TEXT_ORACLE='0')
subprocess.run([sys.executable, 'tools/build.py', 'host'], cwd=ROOT, env=env, check=True)
env['DYN'] = str(BUILD/('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))
for test in ('lsp-navigation', 'shared-host', 'compiler-contracts', 'zero-values',
             'panic-lifetime', 'native-release', 'native-optimization', 'text-output', 'native-assembly', 'cross-runtime', 'wasm-independent', 'wrap-enum-values', 'stdlib-host',
             'sync-host', 'concurrency-net-host'):
    subprocess.run([sys.executable, 'tests/'+test+'.py'], cwd=ROOT, env=env, check=True)
if sys.platform in ('darwin', 'win32'):
    subprocess.run([sys.executable, 'tools/package-host-sdk.py'], cwd=ROOT, env=env, check=True)
    platform_name = 'windows-x86_64' if os.name == 'nt' else 'macos-aarch64'
    report = json.loads((BUILD/'dist'/('package-'+platform_name+'.json')).read_text())
    archive = BUILD/'dist'/report['archive']
    with tempfile.TemporaryDirectory(prefix='dyn-independent-sdk-') as temporary:
        destination = Path(temporary)
        if os.name == 'nt':
            with zipfile.ZipFile(archive) as package:
                package.extractall(destination)
        else:
            with tarfile.open(archive) as package:
                package.extractall(destination, filter='data')
        relocated = dict(env)
        relocated.pop('DYN_SDK', None)
        relocated['DYN'] = str(destination/'dyn-sdk/bin'/('dyn.exe' if os.name == 'nt' else 'dyn'))
        relocated['DYN_TEST_INSTALLED'] = '1'
        for test in ('shared-host', 'stdlib-host', 'cross-runtime', 'wasm-independent'):
            subprocess.run([sys.executable, str(ROOT/'tests'/ (test+'.py'))],
                           cwd=destination, env=relocated, check=True)
print('PASS LLVM-free host compiler and debug/release runtime contracts')
