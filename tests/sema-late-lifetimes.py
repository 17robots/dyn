#!/usr/bin/env python3
"""Lifetime checks on worker threads report what a serial run reports.

Programs with 512 or more functions check every body first and then run
the lifetime checks on worker threads (SemaLate in src/sema.c), replaying
diagnostics in serial order. Each program here mixes proven lifetime
errors, ordinary type errors and dyn vet arena-copy warnings across 600
functions, in several orders, and must print exactly what
DYN_SERIAL_LIFETIMES=1 prints, with the same exit status."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
FUNCTIONS = 600
PLAIN = 'fn f{i}(x: i64) i64 {{\n  y := x * {i} + 1\n  return y - {i}\n}}\n'
LIFETIME = 'fn f{i}(x: i64) *i64 {{\n  y: i64 = x\n  p := &y\n  return p\n}}\n'
TYPE = 'fn f{i}(x: i64) i64 {{\n  y: bool = x\n  return {i}\n}}\n'
ARENA = ('fn f{i}(x: i64) i64 {{\n  storage: [64 + mem.ArenaBufferOverhead]u8\n'
         '  original := mem.arena_from_buffer(storage[..])\n  copy := original.*\n  _ = copy\n  return x\n}}\n')
RESET = ('fn f{i}(x: i64) i64 {{\n  storage: [64]u8\n  a := mem.arena_from_buffer(storage[..])\n'
         '  p := mem.arena_push(a, 8, 1)\n  mem.arena_reset(a)\n  p.* = 7\n  return x\n}}\n')
SHAPES = {
    'clean': {},
    'lifetimes': {40: LIFETIME, 410: LIFETIME},
    'lifetime-then-type': {120: LIFETIME, 300: TYPE, 500: LIFETIME},
    'type-then-lifetime': {90: TYPE, 200: LIFETIME},
    'warnings': {10: ARENA, 333: ARENA, 590: ARENA},
    'warnings-and-errors': {10: ARENA, 250: LIFETIME, 260: ARENA, 400: TYPE},
    'reset': {77: RESET, 300: TYPE},
}
EXPECTED = {'lifetimes': 'borrows function-local', 'lifetime-then-type': 'borrows function-local',
            'warnings': 'copying an arena', 'reset': 'after arena_reset'}
with tempfile.TemporaryDirectory(prefix='dyn-sema-late-') as temporary:
    for shape, special in SHAPES.items():
        project = Path(temporary) / shape
        project.mkdir()
        body = ''.join(special.get(i, PLAIN).format(i=i) for i in range(FUNCTIONS))
        (project / 'main.dyn').write_text('use "std/mem"\n\n' + body + '\nfn main() {}\n')
        for command in (['check'], ['vet'], ['check', '--diagnostics', 'json']):
            runs = []
            for serial in ('1', ''):
                result = subprocess.run([DYN, *command[:1], str(project), '--no-cache', *command[1:]], capture_output=True,
                                        text=True, timeout=120, env={**os.environ, 'DYN_SERIAL_LIFETIMES': serial})
                runs.append((result.returncode, result.stdout, result.stderr))
            assert runs[0] == runs[1], (shape, command, runs)
            if shape in EXPECTED and command[0] == 'vet':
                assert EXPECTED[shape] in runs[0][2], (shape, runs[0])
        if shape != 'clean' and shape != 'warnings':
            assert runs[0][0] != 0, (shape, runs[0])
print('PASS late lifetimes: worker-thread lifetime checks report what serial checks report')
