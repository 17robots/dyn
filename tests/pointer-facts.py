#!/usr/bin/env python3
"""A pointer check carries over only where it dominates later uses: never out
of a branch, a short-circuit operand, or past an assignment or address-of."""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())

PRELUDE = '''struct Node { value: i64 }
fn maybe(flag: bool, node: *Node) *Node {
  if flag { return node }
  return nil
}
'''

# Each body must panic with a nil-pointer check at its last line.
CASES = {
    'short-circuit': '''  p := maybe(false, &node)
  if false && p.value == 1 { return }
  _ = p.value''',
    'branch': '''  p := maybe(false, &node)
  if flag { _ = p.value }
  _ = p.value''',
    'assigned': '''  p := maybe(true, &node)
  _ = p.value
  p = maybe(false, &node)
  _ = p.value''',
    'address-taken': '''  p := maybe(true, &node)
  _ = p.value
  slot := &p
  slot.* = maybe(false, &node)
  _ = p.value''',
    'loop-reassigned': '''  p := maybe(true, &node)
  for i in 0..2 {
    _ = p.value
    p = maybe(false, &node)
    _ = i
  }''',
}

with tempfile.TemporaryDirectory(prefix='dyn-pointer-facts-') as temporary:
    root = Path(temporary)
    for name, body in CASES.items():
        project = root/name
        project.mkdir()
        (project/'main.dyn').write_text(PRELUDE + f'''fn check(flag: bool) {{
  node := Node{{value: 1}}
{body}
}}
fn main() {{
  check(false)
}}
''')
        for release in (False, True):
            output = project/('release' if release else 'debug')
            built = subprocess.run([DYN, 'build', str(project), '--quiet', '--no-cache', '--output', str(output)] +
                                   (['--release'] if release else []), capture_output=True, text=True, timeout=120)
            assert built.returncode == 0, (name, built.stderr)
            run = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
            assert run.returncode != 0, (name, release, 'expected a nil-pointer panic')
            assert 'pointer' in run.stderr or 'nil' in run.stderr, (name, run.stderr)

print('PASS pointer facts: checks do not escape branches, short circuits, assignments or address-of')
