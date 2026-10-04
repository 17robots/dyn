#!/usr/bin/env python3
"""Real ThinLTO must cache native backends and invalidate imported bodies."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

DYN = str(Path(os.environ.get('DYN', './build/dyn-release')).resolve())
if platform.system() != 'Linux' or platform.machine() != 'x86_64' or not shutil.which('ld.lld'):
    print('SKIP ThinLTO requires x86_64 Linux and LLD')
    raise SystemExit(0)

with tempfile.TemporaryDirectory(prefix='dyn-thinlto-') as directory:
    root = Path(directory)
    source = root/'src'
    dependency = source/'value'
    dependency.mkdir(parents=True)
    (source/'main.dyn').write_text('use "./value"\nuse "std/io"\n'
                                  'fn main() { _ = io.println(io.stdout(), value.text()) }\n')
    body = dependency/'main.dyn'
    body.write_text('pub fn text() []const u8 { return "first" }\n')
    cache = root/'cache'
    env = dict(os.environ, DYN_CACHE_DIR=str(cache))
    output = root/'program'

    def build(expected, *options, preserve_output=False):
        # Force linking even when the executable cache would otherwise hit.
        if not preserve_output:
            output.unlink(missing_ok=True)
        result = subprocess.run([DYN, 'build', str(source), '--release', '--jobs', '1',
                                 '--timings', '--output', str(output), *options],
                                env=env, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        result_run = subprocess.run([str(output)], capture_output=True, text=True, timeout=10)
        assert result_run.returncode == 0, result_run.stderr
        assert result_run.stdout.strip() == expected, result_run.stdout
        return result.stderr

    def backends():
        return {p.name: (p.stat().st_mtime_ns, p.read_bytes())
                for p in (cache/'thinlto').glob('llvmcache-*')}

    build('first')
    cold = backends()
    assert cold, 'No ThinLTO backend entries: emission fell back to full LTO'
    warm = build('first')
    assert 'timing detail emit' not in warm, warm
    assert backends() == cold, 'Identical relink regenerated backend cache entries'
    body.write_text('pub fn text() []const u8 { return "second" }\n')
    build('second')
    changed = backends()
    assert changed.keys() > cold.keys(), 'Changed dependency did not invalidate ThinLTO'
    # Keep the old executable to exercise both the fast options key and the
    # object cache: native O2 and ThinLTO must not reuse each other's outputs.
    native = build('second', '--no-lto', preserve_output=True)
    assert 'timing detail emit' in native, 'no-lto reused the ThinLTO executable'
    assert backends() == changed, 'no-lto used the ThinLTO backend cache'
    native_warm = build('second', '--no-lto')
    assert 'timing detail emit' not in native_warm, native_warm
    thin_again = build('second', preserve_output=True)
    assert 'timing link' in thin_again, 'ThinLTO reused a native-only executable'
    fresh = build('second', '--no-cache')
    assert 'timing detail emit' in fresh, fresh
    assert backends() == changed, '--no-cache touched the ThinLTO cache'
    isolated = root/'uncached'
    env['DYN_CACHE_DIR'] = str(isolated)
    build('second', '--no-cache')
    assert not isolated.exists(), '--no-cache created a cache directory'

print('PASS ThinLTO backend reuse, imported-body invalidation, no-lto, and no-cache')
