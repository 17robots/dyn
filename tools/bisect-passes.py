#!/usr/bin/env python3
"""Finds the optimization pass behind a release build that behaves unlike
the debug build. Builds PROJECT in debug as the reference, then in release;
when they differ, rebuilds release once per pass with DYN_SKIP=<pass> and
reports the passes whose absence makes release match debug again.

  tools/bisect-passes.py PROJECT [-- program arguments]

Extra build flags go in BISECT_FLAGS, such as "--opt-level 3"."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
# The optional passes, in pipeline order: IR optimizer first, then SSA.
PASSES = ['inline', 'propagate', 'forward', 'fold', 'cse', 'reuse_loads', 'prove', 'accumulate', 'self_inline', 'jam',
          'hoist', 'unswitch', 'strength', 'thread_conditions', 'selects', 'float_loads', 'vloops', 'pairs',
          'combine_loads', 'combine_stores', 'narrow32', 'rotate64', 'late_lea']


def outcome(project, flags, skip, work, arguments):
    program = work / ('program-' + (skip or 'none').replace(',', '-'))
    environment = {**os.environ, 'DYN_SKIP': skip}
    built = subprocess.run([DYN, 'build', str(project), *flags, '--quiet', '--no-cache', '--output', str(program)],
                           capture_output=True, text=True, timeout=600, env=environment)
    if built.returncode:
        return ('build failed', built.stderr.strip()[-300:])
    try:
        run = subprocess.run([str(program), *arguments], capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return ('timeout',)
    return (run.returncode, run.stdout)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    project = Path(sys.argv[1]).resolve()
    arguments = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    flags = ['--release', *shlex.split(os.environ.get('BISECT_FLAGS', ''))]
    with tempfile.TemporaryDirectory(prefix='dyn-bisect-') as temporary:
        work = Path(temporary)
        reference = outcome(project, ['--debug'], '', work, arguments)
        release = outcome(project, flags, '', work, arguments)
        if release == reference:
            print('release matches debug; nothing to bisect')
            return 0
        print(f'release differs from debug: debug {reference[0]}, release {release[0]}')
        everything = outcome(project, flags, ','.join(PASSES), work, arguments)
        if everything != reference:
            print('release still differs with every optional pass off: the difference is in required lowering, '
                  'register allocation or emission')
            return 1
        culprits = [name for name in PASSES if outcome(project, flags, name, work, arguments) == reference]
        if culprits:
            print('release matches debug without: ' + ', '.join(culprits))
        else:
            print('no single pass explains it; release matches debug only with every optional pass off')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
