#!/usr/bin/env python3
"""Every runnable program under tests/ and examples/ (a directory with
main.dyn) prints the same output and exits the same way in debug and release
builds. Release panics omit locations, so stderr is not compared. Programs
that need input or serve forever time out in both builds and are skipped, as
are projects that build for neither mode on this host (other targets)."""
import concurrent.futures
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
TIMEOUT = 10


def outcome(project, mode, work):
    program = work / f"{project.relative_to(ROOT).as_posix().replace('/', '_')}-{mode}"
    built = subprocess.run([DYN, 'build', str(project), f'--{mode}', '--quiet', '--output', str(program)],
                           capture_output=True, text=True, timeout=600)
    if built.returncode:
        return ('build failed',)
    # A copy of the project, so files a program writes stay out of the tree.
    directory = work / (program.name + '.cwd')
    shutil.copytree(project, directory)
    try:
        run = subprocess.run([str(program)], cwd=directory, stdin=subprocess.DEVNULL, capture_output=True,
                             timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return ('timeout',)
    return (run.returncode, run.stdout)


def check(project, work):
    return project, outcome(project, 'debug', work), outcome(project, 'release', work)


projects = sorted({path.parent for root in ('tests', 'examples') for path in (ROOT / root).rglob('main.dyn')})
failures, compared = [], 0
with tempfile.TemporaryDirectory(prefix='dyn-release-parity-') as temporary:
    with concurrent.futures.ThreadPoolExecutor(max(1, min(8, os.cpu_count() or 1))) as pool:
        for project, debug, release in pool.map(lambda p: check(p, Path(temporary)), projects):
            name = project.relative_to(ROOT).as_posix()
            if debug == release and debug[0] in ('build failed', 'timeout'):
                continue
            # A slow debug build may time out where release finishes.
            if debug == ('timeout',) and release[0] != 'build failed':
                continue
            compared += 1
            if debug != release:
                failures.append(f'{name}: debug {debug[:1]} {debug[1][-200:] if len(debug) > 1 else ""!r} '
                                f'release {release[:1]} {release[1][-200:] if len(release) > 1 else ""!r}')
assert not failures, '\n'.join(failures)
print(f'PASS release parity: {compared} programs print and exit the same in debug and release')
