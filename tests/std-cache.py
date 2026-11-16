#!/usr/bin/env python3
"""std/cache: a zeroed copy is stale, rebuilt makes it current, changed
makes every copy stale, and a version read before a rebuild stays stale when
a write lands during it."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/cache"
use "std/io"

fn main() {
  shared := cache.Shared{}
  first := cache.Copy{}
  second := cache.Copy{}
  seen := cache.stale(&first, &shared)
  io.println("{}", seen != 0)
  cache.rebuilt(&first, seen)
  io.println("{} {}", cache.stale(&first, &shared) == 0, cache.stale(&second, &shared) != 0)
  cache.changed(&shared)
  io.println("{}", cache.stale(&first, &shared) != 0)
  during := cache.stale(&first, &shared)
  cache.changed(&shared)
  cache.rebuilt(&first, during)
  io.println("{}", cache.stale(&first, &shared) != 0)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-std-cache-') as temporary:
    project = Path(temporary) / 'project'
    project.mkdir()
    (project / 'main.dyn').write_text(SOURCE)
    run = subprocess.run([DYN, 'run', str(project)], capture_output=True, text=True, timeout=180)
    assert run.returncode == 0 and run.stdout.endswith('true\ntrue true\ntrue\ntrue\n'), run
print('PASS std/cache: stale, rebuilt, changed, and writes during a rebuild')
