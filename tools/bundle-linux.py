#!/usr/bin/env python3
"""Bundle the Ubuntu-built host toolchain, retaining each dependency's notices."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import hashlib

# glibc and its loader must come from the host as a matching pair.
HOST_LIBS = {'libc.so.6', 'libm.so.6', 'libpthread.so.0', 'libdl.so.2',
             'librt.so.1', 'libresolv.so.2', 'libutil.so.1'}


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def bundle(sdk):
    binary = sdk/'bin/dyn'
    dependencies = run('ldd', str(binary))
    if 'not found' in dependencies:
        raise RuntimeError(dependencies)
    names = re.findall(r'^\s*(\S+) => ', dependencies, re.M)
    if any(name not in HOST_LIBS and Path(name).name not in ('ld-linux-x86-64.so.2', 'ld-linux-aarch64.so.1', 'ld-linux-riscv64-lp64d.so.1') for name in names):
        raise RuntimeError('Unexpected dependency in LLVM-free SDK: '+dependencies)
    versions = re.findall(r'\bGLIBC_(\d+)\.(\d+)\b', run('readelf', '--version-info', str(binary)))
    baseline = max(tuple(map(int, version)) for version in versions)
    header = binary.read_bytes()[:20]
    if header[:6] != b'\x7fELF\x02\x01':
        raise RuntimeError('Expected a little-endian ELF64 compiler')
    architecture = {62: 'x86_64', 183: 'aarch64', 243: 'riscv64'}.get(int.from_bytes(header[18:20], 'little'))
    if architecture is None:
        raise RuntimeError('Unsupported compiler host architecture')
    return dict(os='linux', arch=architecture, glibc_min='.'.join(map(str, baseline)),
                bundled=[], packages={}, backend='native', targets=['x86_64-linux', 'aarch64-linux', 'riscv64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows', 'wasm32-browser', 'wasm32-wasi'])


def runtime_sources(dist, version):
    """Ship the matching independent runtime sources."""
    archive = dist/f'dyn-{version}-runtime-sources.tar.gz'
    with tempfile.TemporaryDirectory(prefix='dyn-runtime-source-') as temporary:
        work = Path(temporary)
        root = Path(__file__).resolve().parents[1]
        shutil.copytree(root/'runtime', work/'runtime')
        shutil.copy2(root/'LICENSE', work/'LICENSE')
        shutil.copy2(root/'tools/build.py', work/'build.py')
        for tool in ('wasm-runtime.py', 'native-runtime.py', 'build-native-support.py'):
            shutil.copy2(root/'tools'/tool, work/tool)
        (work/'README.txt').write_text(
            'Dyn runtime sources for the LLVM-free host SDK. No third-party runtime libraries are bundled.\n'
            'The matching compiler checkout tools/build.py records the independent runtime build commands.\n')
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(work, arcname='runtime-sources')
        return dict(archive=archive.name, sha256=hashlib.sha256(archive.read_bytes()).hexdigest())


if __name__ == '__main__':
    print(json.dumps(bundle(Path(sys.argv[1]).resolve()), indent=2))
