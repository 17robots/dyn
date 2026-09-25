#!/usr/bin/env python3
"""Relocatable macOS/Windows SDKs with private dependencies and their notices."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
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
PLATFORM = 'windows-x86_64' if WINDOWS else 'macos-aarch64'


def run(*command):
    return subprocess.check_output([str(x) for x in command], text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def windows_bundle(sdk):
    prefix = Path(run('llvm-config', '--prefix'))
    binary_dir = prefix/'bin'
    files = {p.name.lower(): p for p in binary_dir.glob('*.dll')}
    tools = sdk/'lib/dyn/tools'; tools.mkdir(parents=True)
    shutil.copy2(binary_dir/'ld.lld.exe', tools/'ld.lld.exe')
    queue = [(sdk/'bin/dyn.exe', BUILD/'dyn-release.exe'),
             (tools/'ld.lld.exe', binary_dir/'ld.lld.exe')]
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
        for name in re.findall(r'^\s*Name: (.+\.dll)\s*$', run('llvm-readobj', '--coff-imports', source), re.M | re.I):
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
    # CLANG64 uses libc++; unexpected GCC/MSYS runtimes need separate qualification.
    if any('gcc' in name or 'stdc++' in name or 'msys-2.0' in name for name in seen):
        raise RuntimeError('Unexpected GNU/MSYS runtime in CLANG64 SDK')
    return dict(platform=PLATFORM, dependencies=sorted(seen), packages=packages, sources=sources)


def macos_bundle(sdk):
    libraries = sdk/'lib/dyn/host'; libraries.mkdir(parents=True)
    tools = sdk/'lib/dyn/tools'; tools.mkdir()
    notices = sdk/'share/dyn/licenses'; notices.mkdir()
    linker = Path(run('brew', '--prefix', 'lld@19'))/'bin/ld64.lld'
    shutil.copy2(linker, tools/'ld64.lld')
    queue = [(sdk/'bin/dyn', BUILD/'dyn-release'), (tools/'ld64.lld', linker)]
    seen = {}; packages = {}

    def notice(source):
        for parent in source.resolve().parents:
            if (parent/'INSTALL_RECEIPT.json').is_file():
                if str(parent) in packages: return
                candidates = [p for p in parent.rglob('*') if p.is_file() and
                              p.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE'))]
                if not candidates: raise RuntimeError('Missing dependency license: '+str(parent))
                directory = notices/(parent.parent.name+'-'+parent.name); directory.mkdir()
                for i, path in enumerate(candidates): shutil.copy2(path, directory/(str(i)+'-'+path.name))
                shutil.copy2(parent/'INSTALL_RECEIPT.json', directory/'INSTALL_RECEIPT.json')
                packages[str(parent)] = parent.parent.name
                return
        raise RuntimeError('No Homebrew provenance for '+str(source))

    for target, source in queue:
        if source != BUILD/'dyn-release': notice(source)
        changes = []
        rpaths = re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset', run('otool','-l',source))
        dependencies = [line.strip().split(' (', 1)[0] for line in run('otool','-L',source).splitlines()[1:]]
        for dependency in dependencies:
            if dependency.startswith(('/usr/lib/', '/System/Library/')): continue
            if dependency.startswith('@loader_path/'):
                original = source.parent/dependency.removeprefix('@loader_path/')
            elif dependency.startswith('@rpath/'):
                candidates = [Path(r.replace('@loader_path', str(source.parent)))/dependency.removeprefix('@rpath/') for r in rpaths]
                candidates += [source.parent/Path(dependency).name]
                original = next((p for p in candidates if p.is_file()), None)
                if original is None: raise RuntimeError('Unresolved Mach-O dependency: '+dependency)
            else:
                original = Path(dependency)
            original = original.resolve()
            if original == source.resolve(): continue  # dylib's own install ID
            destination = libraries/original.name
            if original.name in seen and seen[original.name] != original:
                raise RuntimeError('Conflicting dylib basename: '+original.name)
            if original.name not in seen:
                seen[original.name] = original
                shutil.copy2(original, destination)
                queue.append((destination, original))
            relative = os.path.relpath(destination, target.parent)
            changes += ['-change', dependency, '@loader_path/'+relative]
        if target.suffix == '.dylib': changes += ['-id', '@rpath/'+target.name]
        if changes: run('install_name_tool', *changes, target)
    # Sign after all load commands have been relocated; signatures cover final bytes.
    for target, _ in queue:
        run('codesign', '--force', '--sign', '-', target)
        run('codesign', '--verify', target)
        for line in run('otool','-L',target).splitlines()[1:]:
            dependency = line.strip().split(' (',1)[0]
            if dependency.startswith('/') and not dependency.startswith(('/usr/lib/', '/System/Library/')):
                raise RuntimeError('Unbundled Mach-O dependency: '+dependency)
    return dict(platform=PLATFORM, dependencies=sorted(seen), packages=packages, macos_min='15.0')


if __name__ == '__main__':
    if sys.platform not in ('win32','darwin'): raise SystemExit('Use package-sdk.py for Linux')
    DIST.mkdir(parents=True, exist_ok=True)
    report_path = DIST/f'package-{PLATFORM}.json'
    report_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='dyn-host-package-') as temporary:
        work = Path(temporary); sdk = work/'stage/dyn-sdk'
        subprocess.run([sys.executable, str(ROOT/'tools/install.py'), '--host'], check=True,
                       env=dict(os.environ, DESTDIR=(work/'stage').as_posix(), PREFIX='/dyn-sdk'))
        for name in ('LICENSE','THIRD_PARTY_NOTICES.md','README.md','grammar.lock.json'): shutil.copy2(ROOT/name,sdk/name)
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
