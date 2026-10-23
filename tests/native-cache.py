#!/usr/bin/env python3
"""Native object reuse and executable invalidation through real linker inputs."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import platform
import shlex
import shutil
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
    # Optimization changes must emit independent objects and reuse each one
    # when returning to a previous setting, including a preserved executable.
    changed = build(9, '--opt-level', '1')
    assert 'timing detail native emit' in changed.stderr, changed.stderr
    changed = build(9, '--opt-level', '2')
    assert 'cached native object' in changed.stderr, changed.stderr
    warm = build(9, '--opt-level', '2')
    assert 'cached ' in warm.stdout, warm.stdout
    # Runtime bytes belong to the executable key, not the Dyn object key.
    # Use a private compiler layout so this test never modifies the real SDK.
    private_bin = work/'private-bin'
    private_bin.mkdir()
    compiler = DYN
    shutil.copy2(compiler, private_bin/'dyn')
    for name in ('dynrt_release.o', 'dynrt_support.o'):
        runtime = Path(compiler).parent/name
        if not runtime.exists():
            runtime = Path(compiler).parent/'../lib/dyn'/name
        shutil.copy2(runtime, private_bin/name)
    DYN = str(private_bin/'dyn')
    warm = build(9)
    assert 'cached ' in warm.stdout, warm.stdout
    with (private_bin/'dynrt_support.o').open('ab') as runtime:
        runtime.write(b'cache-runtime-invalidation')
    changed = build(9)
    assert 'cached ' not in changed.stdout, changed.stdout
    assert 'cached native object' in changed.stderr, changed.stderr
    warm = build(9)
    assert 'cached ' in warm.stdout, warm.stdout
    DYN = compiler
    # Real compiler processes race to populate one cold cache. Each output has
    # its own linker destination; only content-addressed objects are shared.
    concurrent_cache = work/'concurrent-cache'
    concurrent_env = dict(env, DYN_CACHE_DIR=str(concurrent_cache))

    def concurrent_build(index):
        destination = work/f'parallel-{index}'
        result = subprocess.run([DYN, 'build', str(source), '--release', '--output',
                                 str(destination), '--link', str(obj)],
                                env=concurrent_env, text=True, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr
        ran = subprocess.run([str(destination)], text=True, capture_output=True, timeout=10)
        assert ran.returncode == 0 and ran.stdout.strip() == '9', (ran.stdout, ran.stderr)

    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(concurrent_build, range(8)))
    assert len(list(concurrent_cache.glob('native-*.o'))) == 1
    assert not list(concurrent_cache.glob('*.??????'))
    fresh = build(9, '--no-cache')
    assert 'timing detail native emit' in fresh.stderr, fresh.stderr

    # Switching from a closed executable to external inputs changes public
    # roots. An object with those symbols pruned cannot serve the second build.
    (source/'main.dyn').write_text('pub fn exported_value() u64 { return 7 }\nfn main() {}\n')
    provider.write_text('extern unsigned long long exported_value(void);\n'
                        '__attribute__((constructor)) static void check_export(void) {\n'
                        '  if (exported_value() != 7) __builtin_trap();\n}\n')
    subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), '-c', str(provider),
                    '-o', str(obj)], check=True)
    command = [DYN, 'build', str(source), '--release', '--verbose', '--timings',
               '--output', str(output)]
    closed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
    assert closed.returncode == 0, closed.stderr
    assert b'exported_value' not in output.read_bytes()
    linked = subprocess.run([*command, '--link', str(obj)], env=env,
                            capture_output=True, text=True, timeout=60)
    assert linked.returncode == 0, linked.stderr
    assert 'timing detail native emit' in linked.stderr, linked.stderr
    assert b'exported_value' in output.read_bytes()
    subprocess.run([str(output)], check=True, timeout=10)
    closed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
    assert closed.returncode == 0 and 'cached native object' in closed.stderr, closed.stderr
    assert b'exported_value' not in output.read_bytes()

print('PASS native cache: linker directives, provider/script edits, corruption, optimization/runtime changes, concurrent builds, cross-output reuse, no-cache')
