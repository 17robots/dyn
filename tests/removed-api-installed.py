#!/usr/bin/env python3
"""Removed-API hints and their dyn fix renames work from an installed SDK,
where std lives in share/dyn/<module> rather than std/<module>."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get('BUILD', ROOT / 'build')).resolve()
SOURCE = '''use "std/mem"

fn main() {
  arena := mem.arena_alloc(0)
  bytes := mem.push_bytes_uninit(arena, 4)
  _ = bytes
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-removed-installed-') as temporary:
    work = Path(temporary)
    prefix = work / 'sdk'
    env = {k: v for k, v in os.environ.items() if k != 'DYN_SDK'}
    subprocess.run([sys.executable, str(ROOT / 'tools/install.py'), '--host'], env=dict(env, PREFIX=str(prefix), BUILD=str(BUILD)),
                   check=True, timeout=120)
    dyn = prefix / 'bin' / ('dyn.exe' if os.name == 'nt' else 'dyn')
    assert (prefix / 'share/dyn/mem/mem.dyn').is_file()
    project = work / 'project'
    project.mkdir()
    (project / 'main.dyn').write_text(SOURCE)
    env['DYN_CACHE_DIR'] = str(work / 'cache')
    checked = subprocess.run([str(dyn), 'check', str(project)], env=env, capture_output=True, text=True, timeout=60)
    assert checked.returncode != 0, checked.stderr
    assert "'mem.push_bytes_uninit' was removed: use mem.push_bytes(arena, count)" in checked.stderr, checked.stderr
    fixed = subprocess.run([str(dyn), 'fix', str(project)], env=env, capture_output=True, text=True, timeout=60)
    text = (project / 'main.dyn').read_text()
    assert 'mem.push_bytes(arena, 4)' in text and fixed.returncode == 0, (fixed.stdout, fixed.stderr, text)
print('PASS removed API from an installed SDK: hint and dyn fix rename')
