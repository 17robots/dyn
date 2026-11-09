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
    assert result.returncode == 0 and result.stdout.endswith('hello 7\n'), result
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
    assert "expected ',' or '}', found 'tag': is a comma missing at the end of the line above" in result.stderr, result.stderr
    (work / 'maps.dyn').write_text('use "std/container/map"\nuse "std/io"\nuse "std/mem"\n\nfn main() {\n'
        '  arena := mem.arena_create(0)\n  ids: map.Map(u64, u32)\n  map.init_integer(&ids, arena)\n'
        '  map.insert(&ids, 9, 4)\n  words: map.Map([]const u8, u32)\n  map.init_text(&words, arena)\n'
        '  map.upsert(&words, "hi", 1).* += 2\n  io.println("{} {}", map.get(&ids, 9).*, map.get(&words, "hi").*)\n}\n')
    result = dyn('run', str(work / 'maps.dyn'))
    assert result.stdout.endswith('4 3\n'), result
    (work / 'entry.dyn').write_text('use "std/container/array"\nuse "std/io"\nuse "std/process"\n\n'
        'fn main(init: process.Init) i32 {\n  words: array.Array([]const u8)\n  array.init(&words, init.arena)\n'
        '  for arg in init.args[1..] {\n    array.push(&words, arg)\n  }\n'
        '  io.println("{} {}", #len(words.items), words.items[0])\n  return #cast(i32, #len(init.args))\n}\n')
    result = dyn('run', str(work / 'entry.dyn'), '--', 'alpha', 'beta')
    assert result.returncode == 3 and result.stdout.endswith('2 alpha\n'), result
    for flags in (['--release'], ['--release', '--opt-level', '3']):
        assert dyn('build', str(work / 'entry.dyn'), *flags, '--quiet', '--output', str(work / 'entry')).returncode == 0
        run = subprocess.run([str(work / 'entry'), 'x'], capture_output=True, text=True)
        assert run.returncode == 2 and run.stdout == '1 x\n', run
    (work / 'badentry.dyn').write_text('fn main(count: i32) {\n  _ = count\n}\n')
    result = dyn('check', str(work / 'badentry.dyn'))
    assert "main's parameter must be an Init struct" in result.stderr, result.stderr
print('PASS single file: run, check, build and fmt a lone file; missing comma named')
