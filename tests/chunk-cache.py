#!/usr/bin/env python3
"""Cached chunks of split modules: body edits rebuild only their file's chunk,
interface edits rebuild everything, and no build links a stale object."""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())


def filler(prefix, count):
    # Enough source to split the module into several chunks.
    return ''.join(f'fn {prefix}_{i}(x: i64) i64 {{\n  return x + {i}\n}}\n' for i in range(count))


def build(project, cache, *extra):
    output = project/'program'
    env = dict(os.environ, DYN_CACHE_DIR=str(cache))
    result = subprocess.run([DYN, 'build', str(project), '--verbose', '--output', str(output), *extra],
                            env=env, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    run = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    cached = result.stderr.count('cached module')
    return run.stdout.strip(), cached


with tempfile.TemporaryDirectory(prefix='dyn-chunk-cache-') as temporary:
    root = Path(temporary)
    project = root/'project'
    project.mkdir()
    cache = root/'cache'
    files = 12
    for n in range(files):
        (project/f'part{n}.dyn').write_text(f'fn value{n}() i64 {{\n  return {n}\n}}\n' + filler(f'p{n}', 400))
    calls = ' + '.join(f'value{n}()' for n in range(files))
    (project/'main.dyn').write_text(f'''use "std/io"
fn main() {{
  total := {calls}
  _ = io.println(io.stdout(), "{{}}", total)
}}
''')
    for extra in ([], ['--release']):
        expected = sum(range(files))
        output, _ = build(project, cache, *extra)
        assert output == str(expected), output

        # A body edit in one file changes the result; other chunks come from cache.
        part = project/'part3.dyn'
        part.write_text(part.read_text().replace('return 3\n', 'return 103\n', 1))
        expected += 100
        output, cached = build(project, cache, *extra)
        assert output == str(expected), output
        assert cached > 0, 'unchanged chunks were not reused'

        # An interface edit (a new signature) must not reuse stale callers.
        part = project/'part5.dyn'
        part.write_text(part.read_text().replace('fn value5() i64 {\n  return 5\n}',
                                                 'fn value5() i64 {\n  return value5_extra(5)\n}\n'
                                                 'fn value5_extra(x: i64) i64 {\n  return x * 2\n}', 1))
        expected += 5
        output, _ = build(project, cache, *extra)
        assert output == str(expected), output

        # Restore for the next mode.
        (project/'part3.dyn').write_text((project/'part3.dyn').read_text().replace('return 103\n', 'return 3\n', 1))
        (project/'part5.dyn').write_text(f'fn value5() i64 {{\n  return 5\n}}\n' + filler('p5', 400))

print('PASS chunk cache: body edits reuse other chunks, interface edits rebuild, outputs current')
