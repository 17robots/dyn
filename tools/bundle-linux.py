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
    libraries = sdk/'lib/dyn/host'
    linkers = sdk/'lib/dyn/tools'
    notices = sdk/'share/dyn/licenses'
    for directory in (libraries, linkers, notices):
        directory.mkdir(parents=True, exist_ok=True)
    packages = {}

    def notice(source):
        if source.name.startswith('libtree-sitter.so'):
            shutil.copy2(sdk/'THIRD_PARTY_NOTICES.md', notices/'tree-sitter.txt')
            return
        # Ubuntu's merged /usr can differ from dpkg's recorded pathname.
        candidates = [str(source), str(source.resolve())]
        candidates += [p.removeprefix('/usr') for p in candidates if p.startswith('/usr/lib/')]
        for candidate in candidates:
            result = subprocess.run(['dpkg-query', '-S', candidate], capture_output=True, text=True)
            if result.returncode == 0:
                package = result.stdout.split(': ', 1)[0]
                break
        else:
            raise RuntimeError('No package provenance for '+str(source))
        name = package.split(':')[0]
        copyright_file = Path('/usr/share/doc')/name/'copyright'
        if not copyright_file.is_file():
            raise RuntimeError('Missing dependency notice: '+package)
        shutil.copy2(copyright_file, notices/(name+'.txt'))
        packages[package] = run('dpkg-query', '-W', '-f=${Version}', package)

    llvm = os.environ.get('LLVM_CONFIG', 'llvm-config-19')
    linker = Path(run(llvm, '--bindir'))/'ld.lld'
    notice(linker.resolve())
    shutil.copy2(linker, linkers/'ld.lld')
    (linkers/'wasm-ld').symlink_to('ld.lld')
    binaries = [sdk/'bin/dyn', linkers/'ld.lld']
    found = {}
    for binary in binaries:
        output = run('ldd', str(binary))
        if 'not found' in output:
            raise RuntimeError(output)
        for name, filename in re.findall(r'^\s*(\S+) => (/\S+) ', output, re.M):
            if name in HOST_LIBS:
                continue
            source = Path(filename)
            if name in found and found[name].resolve() != source.resolve():
                raise RuntimeError('Conflicting dependency: '+name)
            found[name] = source
    for name, source in sorted(found.items()):
        notice(source)
        shutil.copy2(source, libraries/name)
        run('patchelf', '--set-rpath', '$ORIGIN', str(libraries/name))
    run('patchelf', '--set-rpath', '$ORIGIN/../lib/dyn/host', str(binaries[0]))
    run('patchelf', '--set-rpath', '$ORIGIN/../host', str(binaries[1]))
    # Debian copyright files refer to these full license texts.
    shutil.copytree('/usr/share/common-licenses', notices/'common-licenses')
    (notices/'packages.json').write_text(json.dumps(packages, indent=2)+'\n')
    for binary in [*binaries, *libraries.iterdir()]:
        versions = re.findall(r'\bGLIBC_(\d+)\.(\d+)\b', run('readelf', '--version-info', str(binary)))
        if any(tuple(map(int, v)) > (2, 39) for v in versions):
            raise RuntimeError('Host glibc baseline exceeds 2.39: '+str(binary))
        output = run('ldd', str(binary))
        if 'not found' in output:
            raise RuntimeError(output)
        for name, filename in re.findall(r'^\s*(\S+) => (/\S+) ', output, re.M):
            if name not in HOST_LIBS and not Path(filename).resolve().is_relative_to(sdk.resolve()):
                raise RuntimeError('Unbundled dependency: '+name)
    return dict(os='linux', arch='x86_64', glibc_min='2.39', bundled=sorted(found), packages=packages)


def runtime_sources(dist, version):
    """Ship matching GCC source packages alongside its runtime binaries."""
    archive = dist/f'dyn-{version}-runtime-sources.tar.gz'
    with tempfile.TemporaryDirectory(prefix='dyn-runtime-source-') as temporary:
        work = Path(temporary)
        versions = set()
        for package in ('libstdc++6', 'libgcc-s1'):
            value = run('dpkg-query', '-W', '-f=${source:Package}=${source:Version}', package)
            versions.add(value)
        for value in sorted(versions):
            subprocess.run(['apt-get', 'source', '--download-only', '--only-source', value],
                           cwd=work, check=True, timeout=300)
        shutil.copy2(__file__, work/'bundle-linux.py')
        (work/'README.txt').write_text(
            'Corresponding Ubuntu GCC source packages for the bundled GNU runtimes.\n'
            'Extract each .dsc with dpkg-source -x; Debian packaging contains build rules.\n'
            'Dyn copies the runtime libraries unchanged except for ELF RUNPATH, set to\n'
            '$ORIGIN with patchelf; bundle-linux.py records that packaging operation.\n')
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(work, arcname='runtime-sources')
    return dict(archive=archive.name, sha256=hashlib.sha256(archive.read_bytes()).hexdigest())


if __name__ == '__main__':
    print(json.dumps(bundle(Path(sys.argv[1]).resolve()), indent=2))
