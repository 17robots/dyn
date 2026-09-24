#!/usr/bin/env python3
"""Build and verify native raw vendor APIs against the installed C headers.

The output is an SDK overlay. Set DYN_SDK to its directory and add PREFIX/lib
and OVERLAY/lib to DYN_LIBRARY_PATH and LD_LIBRARY_PATH when building/running.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile

LOCATION = Path(__file__).resolve().parents[1]
VENDOR = LOCATION / 'vendor' if (LOCATION / 'vendor').is_dir() else LOCATION / 'share/dyn/vendor'
SOURCE_SDK = VENDOR.parent
DEFAULT_BUILD = LOCATION.parent / 'build' if VENDOR == LOCATION / 'vendor' else Path.cwd() / 'build'
GENERATOR = Path(__file__).with_name('vendor-bindings.py')
if not GENERATOR.is_file():
    GENERATOR = Path(__file__).with_name('dyn-raw-bind')


def run(command, env, **kwargs):
    result = subprocess.run([str(item) for item in command], env=env, text=True,
                            capture_output=True, timeout=600, **kwargs)
    if result.returncode:
        raise RuntimeError(shlex.join(map(str, command)) + '\n' + result.stdout + result.stderr)
    return result.stdout


def header_search(cc, flags, env):
    result = subprocess.run([*cc, *flags, '-E', '-v', '-x', 'c', '-'], input='',
                            env=env, text=True, capture_output=True, check=True, timeout=30)
    text = result.stderr.split('#include <...> search starts here:', 1)[1].split('End of search list.', 1)[0]
    return [Path(line.strip()) for line in text.splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packages', nargs='*', help='Manifest package names; default: every vendor')
    parser.add_argument('--list', action='store_true', help='List package keys and raw import paths without building')
    parser.add_argument('--prefix', type=Path, default=DEFAULT_BUILD / 'vendor-deps/install')
    parser.add_argument('--sources', type=Path, default=DEFAULT_BUILD / 'extra-vendor-sources')
    parser.add_argument('--output', type=Path, default=DEFAULT_BUILD / 'raw-sdk')
    parser.add_argument('--clang', default=os.environ.get('DYN_BIND_CLANG', os.environ.get('CLANG', 'clang')))
    parser.add_argument('--cc', default=os.environ.get('CC', 'cc'))
    parser.add_argument('--dyn', default=str(DEFAULT_BUILD / 'dyn-release') if VENDOR == LOCATION / 'vendor' else str(LOCATION / 'bin/dyn'))
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'aarch64'):
        parser.error('Native generation supports Linux x86_64/aarch64; cross-generation is not supported')
    manifest = json.loads((VENDOR / 'raw-bindings.json').read_text())
    if args.list:
        for name, config in manifest.items():
            print(name + '\tvendor/' + config['module'])
        return
    names = list(dict.fromkeys(args.packages or manifest))
    unknown = set(names) - manifest.keys()
    if unknown:
        parser.error('Unknown providers: ' + ', '.join(sorted(unknown)))
    prefix, sources, output = args.prefix.resolve(), args.sources.resolve(), args.output.resolve()
    if output == SOURCE_SDK.resolve() or output in SOURCE_SDK.resolve().parents or SOURCE_SDK.resolve() in output.parents:
        parser.error('Use a separate output SDK directory')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'lib').mkdir(exist_ok=True)
    env = dict(os.environ)
    for key, value in [('PKG_CONFIG_PATH', str(prefix / 'lib/pkgconfig')),
                       ('LD_LIBRARY_PATH', str(output / 'lib') + ':' + str(prefix / 'lib')),
                       ('DYN_LIBRARY_PATH', str(output / 'lib') + ':' + str(prefix / 'lib'))]:
        env[key] = value + (os.pathsep + env[key] if env.get(key) else '')
    env['DYN_SDK'] = str(output)
    # This subtree is a generated snapshot. Remove obsolete target adapters.
    snapshot = output / 'std'
    if snapshot.is_symlink(): snapshot.unlink()
    elif snapshot.exists(): shutil.rmtree(snapshot)
    standard = SOURCE_SDK / 'std'
    if standard.is_dir():
        shutil.copytree(standard, output / 'std', dirs_exist_ok=True)
    else:
        shutil.copytree(SOURCE_SDK, output / 'std', dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('vendor'))
    shutil.copytree(VENDOR, output / 'vendor', dirs_exist_ok=True)
    cc = shlex.split(args.cc)
    report_path = output / 'raw-bindings-report.json'
    previous = json.loads(report_path.read_text()) if report_path.is_file() else []
    rows = [row for row in previous if row.get('status') == 'passed' and row.get('package') not in names]
    try:
        for name in names:
            config = manifest[name]
            flags = [value.format(sources=sources) for value in config['cflags']]
            package = config.get('pkg_config')
            version = None
            versions = {}
            for dependency in config.get('pkg_config_dependencies', []):
                flags += shlex.split(run(['pkg-config', '--cflags', dependency], env))
                versions[dependency] = run(['pkg-config', '--modversion', dependency], env).strip()
            if package:
                flags += shlex.split(run(['pkg-config', '--cflags', package], env))
                version = run(['pkg-config', '--modversion', package], env).strip()
                versions[package] = version
            includes = header_search(cc, flags, env)
            headers = []
            for header in config['headers']:
                if '*' in header:
                    # Resolve each public header from the compiler's actual search path.
                    found = {}
                    for directory in includes:
                        for path in sorted(directory.glob(header)):
                            found.setdefault(str(path.relative_to(directory)), path)
                    if not found:
                        raise RuntimeError('No headers matched ' + header)
                    headers += list(found)
                else:
                    headers.append(header)
            print('GENERATE ' + name, flush=True)
            with tempfile.TemporaryDirectory(prefix='dyn-vendor-bindings-') as temporary:
                work = Path(temporary)
                generated = work / 'module'
                library = 'dyn_raw_' + name
                command = [sys.executable, GENERATOR, '--output', generated, '--library', library,
                           '--prefix', config['selector'], '--cflags=' + shlex.join(flags),
                           '--clang', args.clang, '--cc', args.cc]
                if config.get('helper_header'):
                    command += ['--helper-header', VENDOR / config['helper_header']]
                for header in headers:
                    command += ['--header', header]
                for link in config['links']:
                    command += ['--link', link]
                for symbol in config.get('procedures', []):
                    command += ['--procedure', symbol]
                if config.get('dispatch'):
                    command += ['--dispatch']
                if config.get('owner'):
                    command += ['--owner', config['owner']]
                run(command, env)
                shared = work / ('lib' + library + '.so')
                run([*cc, '-std=gnu11', '-O2', '-fPIC', '-shared', '-Wno-deprecated-declarations',
                     *flags, generated / 'bridge.c', '-L' + str(prefix / 'lib'),
                     '-Wl,-z,defs', '-Wl,-rpath,$ORIGIN',
                     *['-l' + item for item in config['links']], '-lm', '-pthread', '-ldl',
                     '-o', shared], env)
                # Test with this adapter, not a previous build of the same provider.
                test_env = dict(env)
                for key in ('DYN_LIBRARY_PATH', 'LD_LIBRARY_PATH'):
                    test_env[key] = str(work) + ':' + env[key]
                (generated / 'main.dyn').write_text('fn main() { if !verify_layout() { #panic("C/Dyn layout mismatch") } }\n')
                for mode in ([], ['--release']):
                    run([args.dyn, 'build', generated, '--quiet', '--no-cache', '--max-work', '100000000',
                         '--output', work / 'verify', *mode], test_env)
                    run([work / 'verify'], test_env)
                (generated / 'main.dyn').unlink()
                coverage = json.loads((generated / 'coverage.json').read_text())
                pins = json.loads((VENDOR / 'providers.json').read_text())
                pin_name = 'stb' if name.startswith('stb_') else name
                coverage['provider_version'] = version or pins.get(pin_name, {}).get('version')
                coverage['provider_versions'] = versions
                coverage['provider_revision'] = pins.get(pin_name, {}).get('revision')
                coverage['cflags'] = flags
                coverage['adapter_sha256'] = hashlib.sha256(shared.read_bytes()).hexdigest()
                coverage['validation'] = ['link-no-undefined', 'dyn-debug-layout', 'dyn-release-layout']
                (generated / 'coverage.json').write_text(json.dumps(coverage, indent=2) + '\n')
                destination = output / 'vendor' / config['module']
                destination.mkdir(parents=True, exist_ok=True)
                for file in generated.iterdir():
                    shutil.copy2(file, destination / file.name)
                shutil.copy2(shared, output / 'lib' / shared.name)
                if config.get('example'):
                    example = output / 'examples' / name
                    example.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(VENDOR / config['example'], example / 'main.dyn')
                rows.append(dict(package=name, status='passed', module='vendor/' + config['module'],
                                 functions=coverage['emitted_functions'], records=coverage['records'],
                                 abi_fingerprint=coverage['abi_fingerprint']))
                print('PASS ' + name + ': ' + str(coverage['emitted_functions']) + ' functions', flush=True)
    except BaseException as error:
        rows.append(dict(status='failed', error=str(error)))
        raise
    finally:
        report_path.write_text(json.dumps(rows, indent=2) + '\n')
    print('SDK overlay: ' + str(output))
    activation = ['# Generated POSIX shell environment. Source this file; do not execute it.']
    activation.append('export DYN_SDK=' + shlex.quote(str(output)))
    activation.append('export DYN=' + shlex.quote(shutil.which(args.dyn) or str(Path(args.dyn).resolve())))
    for key in ('DYN_LIBRARY_PATH', 'LD_LIBRARY_PATH'):
        activation.append('export ' + key + '=' + shlex.quote(str(output / 'lib') + ':' + str(prefix / 'lib')) + '"${' + key + ':+:$' + key + '}"')
    (output / 'env.sh').write_text('\n'.join(activation) + '\n')
    print('Activate: . ' + shlex.quote(str(output / 'env.sh')))
    print('DYN_SDK=' + str(output))
    print('DYN_LIBRARY_PATH=' + str(output / 'lib') + ':' + str(prefix / 'lib'))
    print('LD_LIBRARY_PATH=' + str(output / 'lib') + ':' + str(prefix / 'lib'))


if __name__ == '__main__':
    main()
