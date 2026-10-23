#!/usr/bin/env python3
"""Relocatable macOS/Windows SDKs with private dependencies and their notices."""
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get('BUILD', ROOT/'build')).resolve()
DIST = BUILD/'dist'
WINDOWS = sys.platform == 'win32'
ARCH = 'aarch64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x86_64'
PLATFORM = ('windows-' if WINDOWS else 'macos-') + ARCH


def run(*command):
    return subprocess.check_output([str(x) for x in command], text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def windows_bundle(sdk):
    compiler = shutil.which(shlex.split(os.environ.get('CC', 'gcc'))[0])
    if not compiler:
        raise RuntimeError('Cannot locate the native compiler toolchain')
    inspector = shutil.which('objdump') or shutil.which('llvm-objdump')
    if not inspector:
        raise RuntimeError('Packaging requires objdump or llvm-objdump to inspect DLL imports')
    prefix = Path(compiler).resolve().parent.parent
    binary_dir = prefix/'bin'
    files = {p.name.lower(): p for p in binary_dir.glob('*.dll')}
    tools = sdk/'lib/dyn/tools'; tools.mkdir(parents=True)
    queue = [(sdk/'bin/dyn.exe', BUILD/'dyn-release.exe')]
    seen = set()
    packages = {}
    notices = sdk/'share/dyn/licenses'; notices.mkdir()
    system = Path(os.environ['SystemRoot'])/'System32'

    def notice(source):
        posix = run('cygpath', '-u', source)
        package = run('pacman', '-Qoq', posix)
        if package in packages: return
        packages[package] = run('pacman', '-Q', package)
        paths = run('pacman', '-Qlq', package).splitlines()
        licenses = [p for p in paths if '/share/licenses/' in p and not p.endswith('/')]
        if not licenses: raise RuntimeError('Missing dependency license: '+package)
        for i, name in enumerate(licenses):
            src = Path(run('cygpath', '-w', name))
            if src.is_file():
                target = notices/package; target.mkdir(exist_ok=True)
                shutil.copy2(src, target/(str(i)+'-'+src.name))

    while queue:
        target, source = queue.pop(0)
        if target.name.lower() in seen: continue
        seen.add(target.name.lower())
        if source != BUILD/'dyn-release.exe': notice(source)
        imports = re.findall(r'^\s*DLL Name: (.+\.dll)\s*$', run(inspector, '-p', source), re.M | re.I)
        if any('llvm' in name.lower() or 'stdc++' in name.lower() for name in imports):
            raise RuntimeError('Unexpected LLVM/C++ dependency in native SDK')
        for name in imports:
            key = name.lower()
            if key in files:
                destination = sdk/'bin'/files[key].name
                if not destination.exists(): shutil.copy2(files[key], destination)
                queue.append((destination, files[key]))
            elif key.startswith(('api-ms-win-', 'ext-ms-win-')) or (system/name).is_file():
                continue
            else:
                raise RuntimeError('Unresolved DLL: '+name)
    # Preserve complete corresponding source (upstream tarball, patches and recipe).
    iconv = 'mingw-w64-clang-x86_64-libiconv'
    sources = {}
    if iconv in packages:
        if packages[iconv] != iconv+' 1.19-1':
            raise RuntimeError('Update pinned libiconv corresponding source for '+packages[iconv])
        name = 'mingw-w64-libiconv-1.19-1.src.tar.zst'
        url = 'https://mirror.msys2.org/mingw/sources/'+name
        expected = '74428280c17094da5b702c29b2e1a0abae59556ea5dfdd65705cc8ccc1e000fb'
        directory = sdk/'share/dyn/sources'; directory.mkdir()
        with urlopen(url, timeout=60) as response:
            (directory/name).write_bytes(response.read())
        if sha(directory/name) != expected:
            raise RuntimeError('libiconv corresponding source hash mismatch')
        sources[name] = dict(url=url, sha256=expected, package=packages[iconv])
        (directory/'README.txt').write_text(
            'Unmodified MSYS2 libiconv corresponding source, including upstream source,\n'
            'patches and PKGBUILD. Extract with tar; build with makepkg-mingw in CLANG64.\n'
            'The bundled DLL can be replaced with a compatible rebuilt version.\n')
    # The independent GCC build links libgcc statically; no GNU DLL is expected.
    if any('gcc' in name or 'stdc++' in name or 'msys-2.0' in name for name in seen):
        raise RuntimeError('Unexpected GNU/MSYS runtime in CLANG64 SDK')
    return dict(platform=PLATFORM, dependencies=sorted(seen), packages=packages, sources=sources)


def macos_bundle(sdk):
    binary = sdk/'bin/dyn'
    dependencies = [line.strip().split(' (', 1)[0]
                    for line in run('otool', '-L', binary).splitlines()[1:]]
    if any(not name.startswith(('/usr/lib/', '/System/Library/')) for name in dependencies):
        raise RuntimeError('Unexpected dependency in LLVM-free SDK: '+str(dependencies))
    commands = run('otool', '-l', binary)
    minimum = re.search(r'cmd LC_BUILD_VERSION\s+cmdsize \d+\s+platform \S+\s+minos ([0-9.]+)', commands)
    if minimum is None:
        minimum = re.search(r'cmd LC_VERSION_MIN_MACOSX\s+cmdsize \d+\s+version ([0-9.]+)', commands)
    if minimum is None:
        raise RuntimeError('Compiler has no macOS deployment version')
    run('codesign', '--force', '--sign', '-', binary)
    run('codesign', '--verify', binary)
    return dict(platform=PLATFORM, dependencies=dependencies, packages={},
                macos_min=minimum.group(1), backend='native', targets=['x86_64-linux', 'aarch64-linux', 'riscv64-linux', 'riscv64-none', 'riscv32-none', 'riscv32-none-soft', 'thumbv7em-none', 'thumbv7em-none-soft', 'thumbv7em-none-nucleo-h753zi', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows', 'wasm32-browser', 'wasm32-wasi'])


if __name__ == '__main__':
    if sys.platform not in ('win32','darwin'): raise SystemExit('Use package-sdk.py for Linux')
    DIST.mkdir(parents=True, exist_ok=True)
    report_path = DIST/f'package-{PLATFORM}.json'
    report_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='dyn-host-package-') as temporary:
        work = Path(temporary); sdk = work/'stage/dyn-sdk'
        subprocess.run([sys.executable, str(ROOT/'tools/install.py'), '--host'], check=True,
                       env=dict(os.environ, DESTDIR=(work/'stage').as_posix(), PREFIX='/dyn-sdk'))
        for name in ('LICENSE','THIRD_PARTY_NOTICES.md','README.md','CHANGELOG.md'): shutil.copy2(ROOT/name,sdk/name)
        shutil.copytree(ROOT/'docs/migrations', sdk/'docs/migrations')
        distribution = windows_bundle(sdk) if WINDOWS else macos_bundle(sdk)
        compiler = sdk/'bin'/('dyn.exe' if WINDOWS else 'dyn')
        version = run(compiler, 'version').removeprefix('dyn ')
        if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?',version): raise RuntimeError('Invalid version')
        manifest = dict(version=version, distribution=distribution,
                        files={p.relative_to(sdk).as_posix():sha(p) for p in sorted(sdk.rglob('*')) if p.is_file()})
        (sdk/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        archive = DIST/f'dyn-{version}-{PLATFORM}.{ "zip" if WINDOWS else "tar.gz" }'
        if WINDOWS:
            with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
                for p in sorted(sdk.rglob('*')):
                    if p.is_file(): output.write(p, 'dyn-sdk/'+p.relative_to(sdk).as_posix())
        else:
            with tarfile.open(archive,'w:gz') as output: output.add(sdk,arcname='dyn-sdk')
        report_path.write_text(json.dumps(dict(status='packaged',version=version,platform=PLATFORM,
                                               archive=archive.name,sha256=sha(archive),manifest=manifest),indent=2)+'\n')
        print('Packaged:',archive)
