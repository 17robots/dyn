#!/usr/bin/env python3
"""Text cases with more than four patterns dispatch on length and bytes.

Generated cases are checked against a model of their semantics: the empty
string, shared prefixes, many patterns of one length, several patterns per
arm, patterns of 8 bytes and more, `_` anywhere, and bodies that return,
assign, break or continue. On x86-64 Linux a debug build must keep no bounds
checks in the dispatch and a release build must use a jump table. The tree
emitter (DYN_NO_SSA=1) builds them too, in debug as in release.
"""
import os
from pathlib import Path
import platform
import random
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
ALPHABETS = ['ab', 'abc', 'abcdefgh', 'xyz019_', ''.join(chr(c) for c in range(32, 127) if chr(c) not in '"\\{}')]


def word(rng, alphabet):
    length = rng.choice([0, 1, 1, 2, 3, 3, 4, 5, 7, 8, 9, 15, 16, 17, 24])
    return ''.join(rng.choice(alphabet) for _ in range(length))


def program(seed):
    rng = random.Random(seed)
    alphabet = ALPHABETS[seed % len(ALPHABETS)]
    functions, checks = [], []
    for number in range(4):
        used, arms = set(), []
        for _ in range(rng.choice([5, 6, 9, 17, 40, 70])):
            patterns = []
            for _ in range(rng.choice([1, 1, 1, 2, 3])):
                for _ in range(20):
                    text = word(rng, alphabet)
                    if used and rng.random() < 0.4:
                        base = rng.choice(sorted(used))
                        text = base[:rng.randint(0, len(base))] + ''.join(rng.choice(alphabet) for _ in range(rng.randint(0, 3)))
                    if text not in used:
                        used.add(text)
                        patterns.append(text)
                        break
            if patterns:
                arms.append(patterns)
        jumps = []

        def body(value):
            choice = rng.choice([f'{{ return {value} }}', f'{{ hits = {value} }}',
                                 f'{{ hits = {value}\n      return hits }}',
                                 f'{{ if hits == 99 {{ return 0 }}\n      hits = {value} }}'])
            jumps.append(choice.split('\n')[-1].lstrip().startswith('return') or choice.startswith('{ return'))
            return choice
        wildcard = rng.randint(0, len(arms))
        lines = [f'fn pick{number}(key: []const u8) i32 {{', '  hits: i32 = 0', '  case key {']
        for i, patterns in enumerate(arms):
            if i == wildcard:
                lines.append('    _ => ' + body(-7))
            lines.append('    ' + ', '.join(f'"{p}"' for p in patterns) + ' => ' + body(i + 1))
        if wildcard == len(arms):
            lines.append('    _ => ' + body(-7))
        lines += ['  }'] + ([] if all(jumps) else ['  return hits']) + ['}']
        functions.append('\n'.join(lines))
        model = {p: i + 1 for i, patterns in enumerate(arms) for p in patterns}
        probes = sorted(used) + ['']
        for p in sorted(used):
            if p:
                probes += [p[:-1], p + alphabet[0]]
        probes += [word(rng, alphabet) for _ in range(20)]
        checks += [(number, probe, model.get(probe, -7)) for probe in probes]
    main = ['use "std/io"'] + functions + ['fn main() {', '  bad: u32 = 0']
    for i, (number, probe, want) in enumerate(checks):
        main.append(f'  if pick{number}("{probe}") != {want} {{ bad += 1\n    io.println("wrong {i}") }}')
    main += [f'  io.println("checked {{}} {{}}", {len(checks)}, bad)', '}']
    return '\n'.join(main) + '\n', len(checks)


# Bodies that leave a loop: break and continue run at the leaf.
LOOP = '''use "std/io"
fn count(words: [][]const u8) i32 {
  total: i32 = 0
  for w in words {
    case w {
      "alpha" => { total += 1 }
      "beta", "gamma" => { total += 10 }
      "delta" => { continue }
      "epsilon" => { total += 100 }
      "stop" => { break }
      _ => { total += 1000 }
    }
    total += 5
  }
  return total
}
fn main() {
  words: [8][]const u8 = ["alpha", "beta", "delta", "gamma", "zeta", "epsilon", "stop", "alpha"]
  io.println("{}", count(words[..]))
}
'''

# The shape of a command table, with lengths 2 to 8 so the length dispatch
# is dense enough for a jump table; for the machine-code checks below.
TABLE = '''use "std/io"
fn pick(key: []const u8) i32 {
  case key {
    "open" => { return 0 }
    "close" => { return 1 }
    "write" => { return 2 }
    "quit" => { return 3 }
    "reload" => { return 4 }
    "split" => { return 5 }
    "vsplit" => { return 6 }
    "buffer" => { return 7 }
    "cd" => { return 8 }
    "set" => { return 9 }
    "tabnext" => { return 10 }
    "undojoin" => { return 11 }
    _ => { return -1 }
  }
}
keep: fn(key: []const u8) i32 = pick
fn main() {
  io.println("{} {} {}", keep("split"), keep("quit"), keep("nope"))
}
'''


def build(source, mode, level, work, name, tree=False):
    directory = work/name
    directory.mkdir()
    (directory/'main.dyn').write_text(source)
    output = work/f'{name}-bin'
    command = [DYN, 'build', str(directory), '--'+mode, '--no-cache', '--output', str(output)]
    if level:
        command += ['--opt-level', str(level)]
    built = subprocess.run(command, env=dict(os.environ, DYN_NO_SSA='1' if tree else '0'),
                           capture_output=True, text=True, timeout=120)
    assert built.returncode == 0, built.stderr
    return output


with tempfile.TemporaryDirectory(prefix='dyn-text-case-') as temporary:
    work = Path(temporary)
    total = 0
    for seed in range(12):
        source, count = program(seed)
        total += count
        for mode, level, tree in (('debug', None, False), ('release', 2, False), ('release', 3, False),
                                  ('debug', None, True), ('release', 2, True)):
            output = build(source, mode, level, work, f'seed{seed}-{mode}-{level}-{tree}', tree)
            ran = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
            assert ran.returncode == 0 and ran.stdout.endswith(f'checked {count} 0\n'), (seed, mode, level, ran.stdout[-400:])
    for mode, level, tree in (('debug', None, False), ('release', 2, False), ('debug', None, True)):
        output = build(LOOP, mode, level, work, f'loop-{mode}-{tree}', tree)
        ran = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
        # alpha +6, beta +15, delta continues, gamma +15, zeta +1005, epsilon +105, stop breaks.
        assert ran.stdout == '1146\n', (mode, ran.stdout)
    for mode, level in (('debug', None), ('release', 2)):
        output = build(TABLE, mode, level, work, f'table-{mode}')
        ran = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
        assert ran.stdout == '5 3 -1\n', ran.stdout
        if platform.system() == 'Linux' and platform.machine() == 'x86_64' and shutil.which('objdump'):
            assembly = subprocess.check_output(['objdump', '-d', '--no-show-raw-insn', str(output)], text=True)
            body = assembly.split('<pick>:\n')[1].split('\n\n')[0]
            if mode == 'debug':
                assert 'check_failed' not in body, ('dispatch kept bounds checks', body)
            else:
                assert re.search(r'\bjmp\s+\*', body), ('dispatch has no jump table', body)
print(f'PASS text case dispatch: {total} generated lookups in debug and release, SSA and tree emitters, loops, no debug bounds checks, jump tables')
