"""Fixtures and graders for the agent evaluation tasks.

Each grader runs a built tool against the fixtures and returns a list of
(check, passed, detail). The fixtures include unreadable files and a
read-only directory, so grading as root passes checks it should not."""
import os
import shutil
import subprocess
from pathlib import Path

BIG = bytes((index * 7 + index // 997) % 251 for index in range(5_000_000))
REASONS = ('no such', 'not found', 'permission', 'denied', 'invalid', 'missing', 'not a directory',
           'is a directory', 'expected', 'syntax', 'number', 'string', 'exist', 'read', 'parse', 'json',
           'port', 'name', 'space')


def fixtures(root: Path):
    if root.exists():
        subprocess.run(['chmod', '-R', 'u+rwx', str(root)], check=False)
        shutil.rmtree(root)
    root.mkdir(parents=True)

    def write(name, data, mode=None):
        path = root / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
        if mode is not None:
            os.chmod(path, mode)

    for directory in ('adir', 'src', 'srcbad', 'scan1', 'scan2'):
        (root / directory).mkdir()
    write('good.json', '{"name": "web", "port": 8080}')
    write('bad.json', '{"name": "web", "port": }')
    write('noport.json', '{"name": "web"}')
    write('strport.json', '{"name": "web", "port": "x"}')
    write('secret.json', '{"name": "web", "port": 1}', 0)
    write('a.bin', b'alpha\n')
    write('big.bin', BIG)
    write('locked.bin', b'x', 0)
    write('afile', 'x')
    write('src/one.txt', 'a\nb\nc\n')
    write('src/two.txt', 'x\n')
    write('src/skip.md', 'q\n\n')
    write('srcbad/one.txt', 'a\n')
    write('srcbad/locked.txt', 'z\n', 0)
    write('a.txt', 'one\ntwo\n')
    write('empty.txt', '')
    write('locked.txt', 'x\n', 0)
    write('victim.txt', 'v')
    write('m1.txt', 'moved\n')
    write('m2.txt', 'm2\n')
    write('m3.txt', 'm3\n' * 1000)
    write('default.json', '{"name": "def", "port": 9000}')
    write('s-good.json', '{"name": "web", "port": 8080}')
    write('s-bad.json', '{"name": "web", "port": }')
    write('s-locked.json', '{"name": "web", "port": 1}', 0)
    write('s-frac.json', '{"name": "web", "port": 8.5}')
    write('s-zero.json', '{"name": "web", "port": 0}')
    write('s-big.json', '{"name": "web", "port": 70000}')
    write('s-name.json', '{"name": 5, "port": 80}')
    write('scan1/a.json', '{"port": 1}')
    write('scan1/b.json', '{"port": 2}')
    write('scan1/bad.json', '{"port": ')
    write('scan1/noport.json', '{}')
    write('scan1/locked.json', '{"port": 3}', 0)
    write('scan1/frac.json', '{"port": 8.5}')
    write('scan1/notes.txt', 'ignore')
    write('scan1/z.json', '{"port": 26}')
    write('scan2/only.json', '{"port": 7}')
    (root / 'ro').mkdir()
    write('ro/keep.txt', 'keep\n')
    os.chmod(root / 'ro', 0o555)


def run(binary, root, arguments, stdin=''):
    try:
        result = subprocess.run([str(binary), *arguments], input=stdin, capture_output=True, text=True,
                                timeout=30, cwd=root)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 'hang', '', ''


def lines(text):
    return [line for line in text.splitlines() if line.strip()]


def failure(results, tool, name, outcome, needle):
    """A failure case: exit 1, one line naming the tool, the path and a reason, no panic."""
    code, _, err = outcome
    found = lines(err)
    first = found[0] if found else ''
    results.append((f'{tool} {name}: exit 1, one line, no panic',
                    code == 1 and len(found) == 1 and 'stack trace' not in err, f'{code} {found!r}'))
    results.append((f'{tool} {name}: names {tool} and {needle}', first.startswith(tool) and needle in first, first))
    results.append((f'{tool} {name}: gives a reason', any(word in first.lower() for word in REASONS), first))


def grade_config(binary, root, results):
    code, out, err = run(binary, root, ['good.json'])
    results.append(('config ok', code == 0 and out.strip() == 'name=web port=8080', f'{code} {out!r} {err!r}'))
    for name, path in (('missing', 'nope.json'), ('invalid', 'bad.json'), ('no port', 'noport.json'),
                       ('string port', 'strport.json'), ('unreadable', 'secret.json'), ('directory', 'src')):
        failure(results, 'config', name, run(binary, root, [path]), path)


def grade_concat(binary, root, results):
    code, out, err = run(binary, root, ['out.bin', 'a.bin', 'big.bin'])
    joined = (root / 'out.bin').read_bytes() if (root / 'out.bin').exists() else b''
    results.append(('concat ok', code == 0 and joined == b'alpha\n' + BIG, f'{code} {err!r}'))
    for name, arguments, needle in (('missing input', ['out2.bin', 'a.bin', 'nope.bin'], 'nope.bin'),
                                    ('locked input', ['out3.bin', 'a.bin', 'locked.bin'], 'locked.bin'),
                                    ('read-only output', ['ro/out.bin', 'a.bin'], 'ro/out.bin'),
                                    ('output under a file', ['afile/out.bin', 'a.bin'], 'afile/out.bin')):
        failure(results, 'concat', name, run(binary, root, arguments), needle)


def grade_summary(binary, root, results):
    code, out, err = run(binary, root, ['src', 'sumout'])
    path = root / 'sumout/summary.txt'
    written = sorted(lines(path.read_text())) if path.exists() else []
    results.append(('summary ok', code == 0 and written == ['one.txt 3', 'total 4', 'two.txt 1'],
                    f'{code} {written!r} {err!r}'))
    for name, arguments, needle in (('missing source', ['nosrc', 'sumout2'], 'nosrc'),
                                    ('locked file', ['srcbad', 'sumout3'], 'locked.txt'),
                                    ('output is a file', ['src', 'afile'], 'afile'),
                                    ('read-only output', ['src', 'ro/sum'], 'ro/sum')):
        failure(results, 'summary', name, run(binary, root, arguments), needle)


JOBS_INPUT = """count a.txt
copy big.bin big-copy.bin
count nope.txt
bogus thing
remove gone.txt
copy locked.txt x.txt

count empty.txt
copy a.txt ro/new.txt
remove victim.txt
count a.txt
quit
count a.txt
"""


def grade_jobs(binary, root, results):
    code, out, err = run(binary, root, [], JOBS_INPUT)
    results.append(('jobs: finishes', code != 'hang', ''))
    results.append(('jobs: output', lines(out) == ['a.txt 2', 'copied big.bin', 'empty.txt 0', 'removed victim.txt',
                                                   'a.txt 2'], repr(lines(out))))
    found = lines(err)
    results.append(('jobs: five failure lines', len(found) == 5, repr(found)))
    for needle in ('nope.txt', 'bogus', 'gone.txt', 'locked.txt', 'ro/new.txt'):
        results.append((f'jobs: reports {needle}', any(needle in line and line.startswith('jobs') for line in found), ''))
    results.append(('jobs: exit 1', code == 1, str(code)))
    copied = root / 'big-copy.bin'
    results.append(('jobs: copy is exact', copied.exists() and copied.read_bytes() == BIG, ''))
    results.append(('jobs: victim removed', not (root / 'victim.txt').exists(), ''))
    code, out, err = run(binary, root, [], 'count a.txt\n')
    results.append(('jobs: end of input, exit 0', code == 0 and lines(out) == ['a.txt 2'], f'{code} {out!r} {err!r}'))


def grade_move(binary, root, results):
    code, out, err = run(binary, root, ['m1.txt', 'm1-moved.txt'])
    moved = root / 'm1-moved.txt'
    results.append(('move ok', code == 0 and not (root / 'm1.txt').exists() and moved.exists()
                    and moved.read_text() == 'moved\n', f'{code} {err!r}'))
    for name, arguments, keep, absent, needle in (
            ('missing', ['nope.txt', 'out-a.txt'], None, 'out-a.txt', 'nope.txt'),
            ('from a directory', ['adir', 'out-d.txt'], 'adir', 'out-d.txt', 'adir'),
            ('read-only TO', ['m2.txt', 'ro/m2.txt'], 'm2.txt', 'ro/m2.txt', 'ro/m2.txt'),
            ('full device', ['m3.txt', '/dev/full'], 'm3.txt', None, '/dev/full'),
            ('read-only FROM', ['ro/keep.txt', 'kept-copy.txt'], 'ro/keep.txt', None, 'ro/keep.txt')):
        failure(results, 'move', name, run(binary, root, arguments), needle)
        if keep:
            results.append((f'move {name}: FROM kept', (root / keep).exists(), ''))
        if absent:
            results.append((f'move {name}: no partial TO', not (root / absent).exists(), ''))


def grade_settings(binary, root, results):
    code, out, err = run(binary, root, ['s-good.json', 'default.json'])
    results.append(('settings first', code == 0 and out.strip() == 'name=web port=8080 from=s-good.json',
                    f'{code} {out!r} {err!r}'))
    code, out, err = run(binary, root, ['nope.json', 'default.json'])
    results.append(('settings fallback', code == 0 and out.strip() == 'name=def port=9000 from=default.json',
                    f'{code} {out!r} {err!r}'))
    for name, arguments, needle in (('invalid first', ['s-bad.json', 'default.json'], 's-bad.json'),
                                    ('locked first', ['s-locked.json', 'default.json'], 's-locked.json'),
                                    ('directory first', ['adir', 'default.json'], 'adir'),
                                    ('both missing', ['nope.json', 'nope2.json'], 'nope2.json'),
                                    ('fractional port', ['s-frac.json', 'default.json'], 's-frac.json'),
                                    ('zero port', ['s-zero.json', 'default.json'], 's-zero.json'),
                                    ('port too big', ['s-big.json', 'default.json'], 's-big.json'),
                                    ('number name', ['s-name.json', 'default.json'], 's-name.json')):
        outcome = run(binary, root, arguments)
        failure(results, 'settings', name, outcome, needle)
        results.append((f'settings {name}: no output', outcome[1].strip() == '', repr(outcome[1])))


def grade_scan(binary, root, results):
    code, out, err = run(binary, root, ['scan1'])
    results.append(('scan: good lines', sorted(lines(out)) == sorted(['a.json port=1', 'b.json port=2',
                                                                       'z.json port=26', 'good 3 bad 4']),
                    repr(sorted(lines(out)))))
    found = lines(err)
    results.append(('scan: four failure lines', len(found) == 4, repr(found)))
    for needle in ('bad.json', 'noport.json', 'locked.json', 'frac.json'):
        results.append((f'scan: reports {needle}', any(needle in line and line.startswith('scan') for line in found), ''))
    results.append(('scan: exit 1', code == 1, str(code)))
    code, out, err = run(binary, root, ['scan2'])
    results.append(('scan: clean directory', code == 0 and sorted(lines(out)) == ['good 1 bad 0', 'only.json port=7'],
                    f'{code} {out!r} {err!r}'))
    failure(results, 'scan', 'missing directory', run(binary, root, ['nodir']), 'nodir')


GRADERS = {'config': grade_config, 'concat': grade_concat, 'summary': grade_summary, 'jobs': grade_jobs,
           'move': grade_move, 'settings': grade_settings, 'scan': grade_scan}
