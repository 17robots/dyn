#!/usr/bin/env python3
"""Native object reuse and executable invalidation through real linker inputs."""
import os
from pathlib import Path
import platform
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
if platform.system() != 'Linux' or platform.machine() != 'x86_64':
    print('SKIP native cache linker qualification requires x86_64 Linux')
    raise SystemExit(0)

with tempfile.TemporaryDirectory(prefix='dyn-native-cache-') as directory:
    work = Path(directory)
    source = work/'app'
    source.mkdir()
    (source/'main.dyn').write_text('use "std/io"\nextern fn value "value"() i32\n'
                                  'fn main() { _ = io.println(io.stdout(), "{}", value()) }\n')
    provider = work/'provider.c'
    obj = work/'provider.o'
    script = work/'exports.map'
    script.write_text('{ local: value; };\n')
    output = work/'program'
    cache = work/'cache'
    env = dict(os.environ, DYN_CACHE_DIR=str(cache))

    def compile_provider(value):
        provider.write_text(f'int value(void) {{ return {value}; }}\n')
        subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), '-c', str(provider), '-o', str(obj)], check=True)

    def build(expected, *extra):
        command = [DYN, 'build', str(source), '--release', '--verbose', '--timings',
                   '--output', str(output), '--link', str(obj), '--link', '-rpath='+str(work),
                   '--link', '--version-script='+str(script), *extra]
        result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr
        ran = subprocess.run([str(output)], text=True, capture_output=True, timeout=10)
        assert ran.returncode == 0 and ran.stdout.strip() == str(expected), (ran.stdout, ran.stderr)
        return result

    compile_provider(7)
    first = build(7)
    assert 'timing detail native emit' in first.stderr, first.stderr
    warm = build(7)
    assert 'cached ' in warm.stdout and 'timing detail native emit' not in warm.stderr, warm
    # Corrupt final artifact: a valid object must repair it by relinking.
    output.write_bytes(b'corrupt executable')
    repaired = build(7)
    assert 'cached native object' in repaired.stderr, repaired.stderr
    # Native provider body and linker script changes must invalidate the final
    # executable, while preserving the independent Dyn object.
    compile_provider(9)
    changed = build(9)
    assert 'cached native object' in changed.stderr and 'cached ' not in changed.stdout, changed
    script.write_text('{ local: value; another_unused_symbol; };\n')
    changed = build(9)
    assert 'cached native object' in changed.stderr and 'cached ' not in changed.stdout, changed
    changed = build(9, '--link', '--rpath='+str(work/'other'))
    assert 'cached native object' in changed.stderr, changed.stderr
    # The object cache is content-addressed, not tied to a destination filename.
    output = work/'another-program'
    relocated = build(9)
    assert 'cached native object' in relocated.stderr, relocated.stderr
    # Corrupted shared objects must be rejected even when their filenames match.
    artifacts = list(cache.glob('native-*.o'))
    assert len(artifacts) == 1, artifacts
    artifacts[0].write_bytes(b'corrupt object')
    output.unlink()
    rebuilt = build(9)
    assert 'timing detail native emit' in rebuilt.stderr, rebuilt.stderr
    fresh = build(9, '--no-cache')
    assert 'timing detail native emit' in fresh.stderr, fresh.stderr

print('PASS native cache: linker directives, provider/script edits, corruption, cross-output reuse, no-cache')
