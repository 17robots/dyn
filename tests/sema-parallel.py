#!/usr/bin/env python3
"""Parallel body checking produces what the serial loop produces.

Programs with 2048 or more functions check bodies on worker threads
(src/sema_parallel.inc): each worker checks a chunk of functions in place,
with its own copies of the type tables, and the driver commits them in
order, moving their nodes down and checking again serially any function a
worker could not finish (generic instances, diagnostics). The program here
makes each kind of work happen across chunks: array and pointer types new
to a function (the same ones in different chunks, which the commit
interns once), function values, generic calls, loops, `case` and structs.
Its IR must match DYN_SEMA_PARALLEL=0 byte for byte with the default and
with 1, 3 and 7 workers, and it must print what the serial build prints.
Copies with type errors, lifetime errors and vet findings spread through
them must report what the serial check reports, with the same status
(`dyn vet` checks serially: its findings go to lists the run shares)."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
FUNCTIONS = 2400


def function(i):
    size = i % 37 + 1
    value = f'f{i - 1}' if i else 'base'
    generic = f'  total += #cast(i64, same(#cast(u{8 << (i % 4)}, x)))\n' if i % 97 == 5 else ''
    return f'''fn f{i}(x: i64) i64 {{
  numbers: [{size}]u16
  numbers[{i % size}] = #cast(u16, x & 255)
  view := &numbers
  values: [3]i64 = [x, {i}, 2]
  total: i64 = 0
  for v in values[..] {{
    total += v
  }}
  case x % 3 {{
    0 => {{ total += 1 }}
    1 => {{ total ^= {i} }}
    _ => {{ total -= 1 }}
  }}
  pair := Pair{{left: total, right: #cast(i64, view.*[{i % size}])}}
  next := {value}
  _ = next
{generic}  return pair.left + pair.right + #cast(i64, #len(numbers))
}}
'''


HEAD = '''use "std/io"
use "std/mem"

struct Pair { left: i64, right: i64 }

fn same(x: $T) T {
  return x
}

fn base(x: i64) i64 {
  return x
}

'''
MAIN = '''
fn main() {
  total: i64 = 0
  for i in 0..''' + str(FUNCTIONS) + ''' {
    total += #cast(i64, i)
  }
  total += f0(1) + f1(2) + f''' + str(FUNCTIONS // 2) + '''(3) + f''' + str(FUNCTIONS - 1) + '''(4)
  io.println("{}", total)
}
'''
LIFETIME = 'fn f{i}(x: i64) *i64 {{\n  y: i64 = x\n  p := &y\n  return p\n}}\n'
TYPE = 'fn f{i}(x: i64) i64 {{\n  y: bool = x\n  return {i}\n}}\n'
ARENA = ('fn f{i}(x: i64) i64 {{\n  storage: [64 + mem.ArenaBufferOverhead]u8\n'
         '  original := mem.arena_from_buffer(storage[..])\n  copy := original.*\n  _ = copy\n  return x\n}}\n')
BROKEN = {
    'type': {300: TYPE, 1800: TYPE},
    'lifetime': {40: LIFETIME, 2210: LIFETIME},
    'mixed': {90: ARENA, 700: LIFETIME, 1200: TYPE, 1201: ARENA, 2300: LIFETIME},
}
MODES = {'serial': '0', 'default': '', 'one': '1', 'three': '3', 'seven': '7'}


def run(*args, mode, extra=None):
    env = {**os.environ, 'DYN_SEMA_PARALLEL': MODES[mode], **(extra or {})}
    return subprocess.run([DYN, *args], capture_output=True, timeout=300, env=env)


with tempfile.TemporaryDirectory(prefix='dyn-sema-parallel-') as temporary:
    project = Path(temporary) / 'clean'
    project.mkdir()
    (project / 'main.dyn').write_text(HEAD + ''.join(function(i) for i in range(FUNCTIONS)) + MAIN)
    dumps = {}
    for mode in MODES:
        result = run('build', str(project), '--no-cache', '--emit-ir', mode=mode)
        assert result.returncode == 0, (mode, result.stderr.decode()[-2000:])
        dumps[mode] = result.stdout
    for mode in MODES:
        assert dumps[mode] == dumps['serial'], (mode, 'IR differs from serial checking')
    outputs = {}
    for mode in ('serial', 'default'):
        program = Path(temporary) / f'run-{mode}'
        built = run('build', str(project), '--no-cache', '--quiet', '--output', str(program), mode=mode)
        assert built.returncode == 0, (mode, built.stderr.decode()[-2000:])
        outputs[mode] = subprocess.run([str(program)], capture_output=True, text=True, timeout=60, check=True).stdout
    assert outputs['default'] == outputs['serial'] and outputs['serial'].strip(), outputs

    for shape, special in BROKEN.items():
        broken = Path(temporary) / shape
        broken.mkdir()
        body = ''.join(special.get(i, '').format(i=i) or function(i) for i in range(FUNCTIONS))
        (broken / 'main.dyn').write_text(HEAD + body + '\nfn main() {}\n')
        for command in (['check'], ['vet']):
            for lifetimes in ('1', ''):
                runs = {}
                for mode in ('serial', 'default', 'three'):
                    result = run(command[0], str(broken), '--no-cache', mode=mode,
                                 extra={'DYN_SERIAL_LIFETIMES': lifetimes})
                    runs[mode] = (result.returncode, result.stdout, result.stderr)
                for mode in runs:
                    assert runs[mode] == runs['serial'], (shape, command, lifetimes, mode, runs[mode], runs['serial'])
                assert runs['serial'][0] != 0 or command[0] == 'vet', (shape, command, runs['serial'])
print('PASS parallel sema: IR, output and diagnostics match serial checking with 1 to 7 workers')
