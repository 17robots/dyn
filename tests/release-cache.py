#!/usr/bin/env python3
"""Native release cache must invalidate imported bodies."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile

DYN = str(Path(os.environ.get('DYN', './build/dyn-release')).resolve())
if platform.system() != 'Linux' or platform.machine() != 'x86_64':
    print('SKIP release cache qualification requires x86_64 Linux')
    raise SystemExit(0)

with tempfile.TemporaryDirectory(prefix='dyn-release-cache-') as directory:
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

    build('first')
    warm = build('first', preserve_output=True)
    assert 'timing detail native emit' not in warm, warm
    body.write_text('pub fn text() []const u8 { return "second" }\n')
    changed = build('second', preserve_output=True)
    assert 'timing detail native emit' in changed, changed
    fresh = build('second', '--no-cache')
    assert 'timing detail native emit' in fresh, fresh
    isolated = root/'uncached'
    env['DYN_CACHE_DIR'] = str(isolated)
    build('second', '--no-cache')
    assert not isolated.exists(), '--no-cache created a cache directory'

print('PASS native release cache reuse, imported-body invalidation and no-cache')
