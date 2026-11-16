#!/usr/bin/env python3
"""Runtime cache inputs on a Linux host."""
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve()


def run(command, **kwargs):
    result = subprocess.run(list(map(str, command)), capture_output=True,
                            text=True, timeout=60, **kwargs)
    assert result.returncode == 0, (command, result.stdout, result.stderr)
    return result




with tempfile.TemporaryDirectory(prefix='dyn-runtime-audit-') as temporary:
    root = Path(temporary)
    if platform.system() == 'Linux' and platform.machine().lower() in ('x86_64', 'amd64'):
        objcopy = shutil.which('llvm-objcopy') or shutil.which('objcopy')
        assert objcopy, 'runtime cache regression requires objcopy'
        sdk = root / 'sdk'
        binary = sdk / 'bin'
        binary.mkdir(parents=True)
        compiler = binary / 'dyn'
        shutil.copy2(DYN, compiler)
        shutil.copytree(ROOT / 'std', sdk / 'std')
        for name in ('dynrt_start.o', 'dynrt_release.o', 'dynrt_support.o'):
            source = DYN.parent / name
            if not source.exists():
                source = DYN.parent.parent / 'lib/dyn' / name
            shutil.copy2(source, binary / name)
        project = root / 'app'
        project.mkdir()
        (project / 'main.dyn').write_text('fn main() {}\n')
        env = dict(os.environ, DYN_SDK=str(sdk), DYN_CACHE_DIR=str(root / 'cache'))

        for release in (False, True):
            output = root / ('program-release' if release else 'program-debug')
            command = [compiler, 'build', project, '--output', output,
                       '--jobs', '1', '--timings', *(['--release'] if release else [])]
            cold = run(command, env=env)
            assert 'timing link' in cold.stderr, cold.stderr
            warm = run(command, env=env)
            assert 'timing link' not in warm.stderr, warm.stderr
            for name in ('dynrt_release.o' if release else 'dynrt_start.o',
                         'dynrt_support.o'):
                runtime = binary / name
                original = runtime.read_bytes()
                marker = root / 'marker'
                marker.write_bytes(b'runtime fingerprint regression\n')
                replacement = root / 'changed.o'
                run([objcopy, '--add-section', f'.dyn.runtime.audit={marker}',
                     runtime, replacement])
                runtime.write_bytes(replacement.read_bytes())
                assert runtime.read_bytes() != original
                changed = run(command, env=env)
                assert 'timing link' in changed.stderr, (
                    name, release, 'changed runtime reused executable cache', changed.stderr)
                run([output])
                unchanged = run(command, env=env)
                assert 'timing link' not in unchanged.stderr, unchanged.stderr
                # A cached executable must not conceal missing or corrupt
                # selected runtime inputs. Only this disposable SDK is edited.
                runtime.unlink()
                missing = subprocess.run(list(map(str, command)), env=env,
                                         capture_output=True, text=True, timeout=60)
                assert missing.returncode != 0, (name, release, 'missing runtime cache hit')
                runtime.write_bytes(b'not an object file\n')
                corrupt = subprocess.run(list(map(str, command)), env=env,
                                         capture_output=True, text=True, timeout=60)
                assert corrupt.returncode != 0, (name, release, 'corrupt runtime cache hit')
                runtime.write_bytes(original)
                run(command, env=env)
        print('PASS isolated runtime-object cache invalidation (debug/release)')
    else:
        print('SKIP x86-64 Linux runtime cache fixture: requires matching host')

