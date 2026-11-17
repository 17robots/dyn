#!/usr/bin/env python3
"""Fixes on diagnostics, and `dyn fix` over the corpus in tests/fix-corpus.

Each corpus case is a module with mistakes an agent or a person moving code
from another language or an older Dyn makes. `dyn fix` must turn every X.dyn
into X.dyn.expected, apply nothing on a second run, and leave exactly the
diagnostics listed in remaining.txt (none means the module checks clean).
Only certain fixes are applied; a suggestion stays for a person to judge."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
CORPUS = ROOT / 'tests/fix-corpus'

def run(*arguments):
    return subprocess.run([DYN, *arguments], capture_output=True, text=True, timeout=120)

cases = sorted(path for path in CORPUS.iterdir() if path.is_dir())
solved = 0
with tempfile.TemporaryDirectory(prefix='dyn-fix-corpus-') as temporary:
    for case in cases:
        project = Path(temporary) / case.name
        shutil.copytree(case, project)
        fixed = run('fix', str(project))
        for expected in sorted(case.glob('*.dyn.expected')):
            actual = (project / expected.name.removesuffix('.expected')).read_text()
            assert actual == expected.read_text(), (case.name, expected.name, actual)
        remaining = [line for line in (case / 'remaining.txt').read_text().splitlines() if line]
        for line in remaining:
            assert line in fixed.stderr, (case.name, line, fixed.stderr)
        assert (fixed.returncode == 0) == (not remaining), (case.name, fixed.returncode, fixed.stderr)
        again = run('fix', str(project))
        assert '0 fixes applied' in again.stdout, (case.name, again.stdout)
        solved += not remaining
    # JSON carries the fix with its byte offset, and whether dyn fix applies it.
    project = Path(temporary) / 'json'
    project.mkdir()
    (project / 'main.dyn').write_text('use "std/mem"\nfn main() {\n  a := mem.arena_alloc(0)\n'
                                      '  _ = mem.push_bytes_uninit(a, 1)\n  _ = mem.push_aray(u8, a, 1)\n}\n')
    reports = [json.loads(line) for line in run('check', str(project), '--diagnostics', 'json').stderr.splitlines()]
    renamed, guessed = reports
    source = (project / 'main.dyn').read_text().encode()
    fix = renamed['fix']
    assert fix['certain'] and fix['replacement'] == 'push_bytes', renamed
    assert source[fix['offset']:fix['offset'] + fix['length']] == b'push_bytes_uninit', fix
    assert fix['range']['start'] == {'line': 4, 'column': 11}, fix
    assert not guessed['fix']['certain'] and guessed['fix']['replacement'] == 'push_array', guessed
    # Text output shows the fix under the snippet.
    text = run('check', str(project)).stderr
    assert " fix: replace 'push_bytes_uninit' with 'push_bytes'" in text, text
    assert " suggestion: replace 'push_aray' with 'push_array'" in text, text
print(f'PASS diagnostic fixes: JSON and text fixes; dyn fix solves {solved} of {len(cases)} corpus modules '
      'and leaves the expected diagnostics in the rest')
