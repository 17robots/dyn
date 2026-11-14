#!/usr/bin/env python3
"""Every program in examples/ is formatted, passes dyn vet, and replays its
recorded session in debug and release builds.

Each project's session.txt is a transcript: `$ name ARGS` lines, then what the
program printed (standard output and error, in order) and `[exit N]` when it
did not exit 0. Runs happen in a fresh copy of the project directory, so a
program may create files there. `--update` rewrites the transcripts from a
debug build instead of comparing.
"""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())
EXAMPLES = ROOT / 'examples'

# Each step is (arguments, standard input file or None, whether to show
# standard error). Standard error is hidden where its content depends on
# thread scheduling.
SESSIONS = {
    'tour': [([], None, True)],
    '01-life': [([], None, True)],
    '02-wordcount': [
        (['poem.txt', 'words.txt'], None, True),
        (['poem.txt', 'missing.txt'], None, True),
        ([], 'poem.txt', True),
    ],
    '03-todo': [
        (['list'], None, True),
        (['add', 'buy', 'oat', 'milk'], None, True),
        (['add', 'write', 'the', 'docs'], None, True),
        (['add', 'call', 'the', 'plumber'], None, True),
        (['done', '2'], None, True),
        (['list'], None, True),
        (['remove', '1'], None, True),
        (['done', '7'], None, True),
        (['done', 'two'], None, True),
        (['clear'], None, True),
        (['list'], None, True),
        (['rename', '1'], None, True),
    ],
    '04-journal': [([], 'commands.txt', True)],
    '05-calc': [([], 'input.txt', True)],
    '06-ledger': [(['expenses.csv'], None, True)],
    '07-editor': [([], 'script.txt', True)],
    '08-site': [
        (['pages', 'out'], None, True),
        (['missing', 'out'], None, True),
    ],
    '09-primes': [
        (['1000000', '4'], None, False),
        (['100', '1'], None, False),
    ],
}

# Files a session must leave behind, compared with expected/<same name>.
OUTPUTS = {
    '08-site': ['out/index.html', 'out/arenas.html', 'out/errors.html', 'out/welcome.html'],
}


def program_name(project):
    return project.split('-', 1)[-1]


def transcript(binary, project, directory):
    lines = []
    for arguments, stdin_name, show_errors in SESSIONS[project]:
        command = ' '.join([program_name(project), *map(shlex.quote, arguments)])
        if stdin_name:
            command += f' < {stdin_name}'
        if not show_errors:
            command += ' 2>/dev/null'
        lines.append(f'$ {command}\n')
        stdin = open(directory / stdin_name, 'rb') if stdin_name else subprocess.DEVNULL
        try:
            run = subprocess.run([str(binary), *arguments], cwd=directory, stdin=stdin,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT if show_errors else subprocess.DEVNULL,
                                 timeout=120)
        finally:
            if stdin_name:
                stdin.close()
        lines.append(run.stdout.decode())
        if run.returncode != 0:
            lines.append(f'[exit {run.returncode}]\n')
    return ''.join(lines)


def main():
    update = '--update' in sys.argv[1:]
    projects = sorted(p.name for p in EXAMPLES.iterdir() if (p / 'main.dyn').is_file() and p.name != 'box-viewer')
    missing = sorted(set(projects) ^ set(SESSIONS))
    if missing:
        raise SystemExit(f'FAIL examples: sessions and directories differ: {missing}')
    failures = []
    with tempfile.TemporaryDirectory(prefix='dyn-examples-') as temporary:
        for project in projects:
            source = EXAMPLES / project
            subprocess.run([DYN, 'fmt', '--check', str(source)], check=True, timeout=60)
            vet = subprocess.run([DYN, 'vet', str(source)], capture_output=True, text=True, timeout=120)
            if vet.returncode != 0:
                failures.append(f'{project}: dyn vet\n{vet.stdout}{vet.stderr}')
                continue
            expected_path = source / 'session.txt'
            modes = [[]] if update else [[], ['--release']]
            for mode in modes:
                binary = Path(temporary) / f'{project}{"-release" if mode else ""}'
                subprocess.run([DYN, 'build', str(source), *mode, '--quiet', '--no-cache',
                                '--output', str(binary)], check=True, timeout=300)
                directory = Path(temporary) / f'run-{project}{"-release" if mode else ""}'
                shutil.copytree(source, directory)
                actual = transcript(binary, project, directory)
                if update:
                    expected_path.write_text(actual)
                    for name in OUTPUTS.get(project, []):
                        target = source / 'expected' / Path(name).name
                        target.parent.mkdir(exist_ok=True)
                        shutil.copyfile(directory / name, target)
                    continue
                label = f'{project} {"release" if mode else "debug"}'
                if actual != expected_path.read_text():
                    failures.append(f'{label}: session differs\n{actual}')
                for name in OUTPUTS.get(project, []):
                    produced = directory / name
                    wanted = source / 'expected' / Path(name).name
                    if not produced.is_file() or produced.read_bytes() != wanted.read_bytes():
                        failures.append(f'{label}: {name} differs from expected/{wanted.name}')
    if failures:
        raise SystemExit('FAIL examples\n' + '\n'.join(failures))
    if update:
        print(f'UPDATED examples: {len(projects)} session transcripts')
    else:
        print(f'PASS examples: {len(projects)} programs formatted, vetted and replayed in debug and release')


main()
