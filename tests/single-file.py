#!/usr/bin/env python3
"""A lone .dyn file runs, checks, builds and formats as a module of one file,
beside other files it does not load; a missing comma between items on
separate lines says so."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())

def dyn(*args, cwd=None):
    return subprocess.run([DYN, *args], capture_output=True, text=True, timeout=120, cwd=cwd)

with tempfile.TemporaryDirectory(prefix='dyn-single-') as directory:
    work = Path(directory)
    (work / 'hello.dyn').write_text('use "std/io"\n\nfn main() {\n  io.println("hello {}", 7)\n}\n')
    # Another program in the same directory is not part of hello.dyn.
    (work / 'other.dyn').write_text('fn main() {\n  x: u8 = true\n}\n')
    result = dyn('run', str(work / 'hello.dyn'))
    assert result.returncode == 0 and result.stdout.startswith('hello 7\n'), result
    result = dyn('check', str(work / 'other.dyn'))
    assert result.returncode != 0 and str(work / 'other.dyn') + ':2:3' in result.stderr, result.stderr
    result = dyn('build', 'hello.dyn', '--quiet', cwd=work)
    assert result.returncode == 0, result.stderr
    assert subprocess.run([str(work / 'hello')], capture_output=True, text=True).stdout == 'hello 7\n'
    (work / 'ugly.dyn').write_text('fn main() {\n    x := 1\n  _ = x\n}\n')
    assert dyn('fmt', '--check', str(work / 'ugly.dyn')).returncode != 0
    assert dyn('fmt', str(work / 'ugly.dyn')).returncode == 0
    assert (work / 'ugly.dyn').read_text() == 'fn main() {\n  x := 1\n  _ = x\n}\n'
    (work / 'comma.dyn').write_text('struct Cell {\n  hp: i32 = 7\n  tag: u8\n}\n\nfn main() {}\n')
    result = dyn('check', str(work / 'comma.dyn'))
    assert "expected ',' or '}', found 'tag': items on separate lines still need a comma" in result.stderr, result.stderr
    (work / 'maps.dyn').write_text('use "std/container/map"\nuse "std/io"\nuse "std/mem"\n\nfn main() {\n'
        '  arena := mem.arena_create(0)\n  ids: map.Map(u64, u32)\n  map.init_integer(&ids, arena)\n'
        '  map.insert(&ids, 9, 4)\n  words: map.Map([]const u8, u32)\n  map.init_text(&words, arena)\n'
        '  map.upsert(&words, "hi", 1).* += 2\n  io.println("{} {}", map.get(&ids, 9).*, map.get(&words, "hi").*)\n}\n')
    result = dyn('run', str(work / 'maps.dyn'))
    assert result.stdout.startswith('4 3\n'), result
print('PASS single file: run, check, build and fmt a lone file; missing comma named')
