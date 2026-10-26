#!/usr/bin/env python3
"""dyn fmt: canonical indentation, idempotence, comment preservation, clean std."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())


def fmt(directory, *options):
    return subprocess.run([DYN, 'fmt', *options, str(directory)], capture_output=True, text=True, timeout=60)


def comments(text):
    return sorted(m.group(0).strip() for m in re.finditer(r'//[^\n]*|/\*.*?\*/', text, re.S))


MESSY = '''fn add(
        left: i64,
          right: i64) i64 {
      total := left +
right
         /* block
     comment kept verbatim */
  return total // trailing
}
fn main() {
        if add(1, 2) == 3 &&
    add(2, 2) == 4 {
x := [1, 2,
  3]
          _ = x
    } else {
  #panic("add")
        }
}
'''
EXPECTED = '''fn add(
  left: i64,
  right: i64) i64 {
  total := left +
    right
  /* block
     comment kept verbatim */
  return total // trailing
}
fn main() {
  if add(1, 2) == 3 &&
    add(2, 2) == 4 {
    x := [1, 2,
      3]
    _ = x
  } else {
    #panic("add")
  }
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-formatter-') as temporary:
    work = Path(temporary)
    project = work / 'messy'
    project.mkdir()
    (project / 'main.dyn').write_text(MESSY)
    assert fmt(project, '--check').returncode == 1
    assert fmt(project).returncode == 0
    formatted = (project / 'main.dyn').read_text()
    assert formatted == EXPECTED, formatted
    assert fmt(project, '--check').returncode == 0
    built = subprocess.run([DYN, 'build', str(project), '--quiet', '--no-cache', '--output', str(work / 'program')],
                           capture_output=True, text=True, timeout=120)
    assert built.returncode == 0, built.stderr
    assert subprocess.run([str(work / 'program')], timeout=10).returncode == 0

    # Every std, runtime and vendor module stays formatted. Flattening their
    # indentation and reformatting reproduces them exactly, keeping comments.
    directories = sorted({path.parent for top in ('std', 'runtime', 'vendor')
                          for path in (ROOT / top).rglob('*.dyn')})
    for index, directory in enumerate(directories):
        check = fmt(directory, '--check')
        assert check.returncode == 0, (directory, check.stderr)
        copy = work / str(index)
        shutil.copytree(directory, copy)
        originals = {path.name: path.read_text() for path in copy.glob('*.dyn')}
        for path in copy.glob('*.dyn'):
            text = originals[path.name]
            # Block comment interiors keep their own indentation, so only flatten code lines.
            flattened, inside = [], False
            for line in text.split('\n'):
                flattened.append(line if inside else '      ' + line.lstrip(' '))
                if '/*' in line and '*/' not in line.split('/*', 1)[1]:
                    inside = True
                elif '*/' in line:
                    inside = False
            path.write_text('\n'.join(flattened))
        assert fmt(copy).returncode == 0
        for path in copy.glob('*.dyn'):
            again = path.read_text()
            assert again == originals[path.name], (directory / path.name)
            assert comments(again) == comments(originals[path.name]), (directory / path.name)
print(f'PASS dyn fmt indentation, idempotence and comments; {len(directories)} std/runtime/vendor modules formatted')
