#!/usr/bin/env python3
"""Arena-owned Thompson regexes; deterministic Python-re subset differential."""
import json
import os
from pathlib import Path
import random
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
rng = random.Random(7391)
cases = [('a{0}', ''), ('(a)*', 'aaaa'), ('(a*)a', 'aaaa'),
         ('(a)b|(a)c', 'ac'), ('(a|aa)*b', 'a' * 16),
         ('(a){200}', 'a' * 200), ('(a?)*b', 'aaab')]
for _ in range(160):
    atom = rng.choice(['a', 'b', '[ab]', '[^b]', '.', '(ab|a)', '(a|b)'])
    pattern = rng.choice(['', '^']) + atom + rng.choice(['', '*', '+', '?', '{0}', '{2}', '{1,3}', '{2,}']) + rng.choice(['', 'b', '$'])
    text = ''.join(rng.choice('abc') for _ in range(rng.randrange(15)))
    cases.append((pattern, text))
checks = []
for index, (pattern, text) in enumerate(cases):
    match = re.search(pattern, text)
    expected = 'false' if match is None else 'true'
    span = '' if match is None else f' && r.value.start == {match.start()} && r.value.end == {match.end()}'
    checks.append(f'''if true {{
    p := regex.compile(&arena, {json.dumps(pattern)})
    require(p.ok, "compile {index}")
    before := mem.arena_used(&arena)
    for repeat in 0..3 {{
      r := regex.find(p.value, {json.dumps(text)})
      require(r.ok && r.value.ok == {expected}{span}, "case {index}")
      require(mem.arena_used(&arena) == before, "match allocated")
    }}
  }}''')
source = '''use "std/text/regex" regex
use "std/mem" mem
use "std/errors" errors
fn require(ok: bool, message: []const u8) { if !ok { #panic(message) } }
fn main() {
  arena: mem.Arena
  defer { mem.arena_release(&arena) }
  pattern: [3]u8 = ['a', '+', 'b']
  first := regex.compile(&arena, pattern[..])
  second := regex.compile(&arena, "b+")
  pattern[0] = 'z'
  require(first.ok && second.ok && regex.matches(first.value, "aaab") && regex.matches(second.value, "bbb"), "independent owned patterns")
  invalid_program: regex.Program
  invalid_match := regex.find(invalid_program, "a")
  require(!invalid_match.ok && invalid_match.kind == errors.Kind.InvalidState && invalid_match.error == 0, "zero program")
  mark := mem.arena_used(&arena)
''' + '\n'.join(
    f'  bad{n} := regex.compile(&arena, {json.dumps(pattern)} )\n'
    f'  require(!bad{n}.ok && bad{n}.kind == errors.Kind.InvalidInput && bad{n}.error == 0 && bad{n}.offset == {offset}, "invalid offset {n}")\n'
    for n, (pattern, offset) in enumerate([('(', 0), ('ab)', 2), ('ab[', 2), ('ab\\', 2), ('a**', 2), ('a{2,1}', 1), ('', 0), ('a{18446744073709551616}', 1), ('(' * 129 + 'a' + ')' * 129, 128)])
) + '''
  require(mem.arena_used(&arena) == mark, "invalid allocated")
  captured := regex.compile(&arena, "(a)b|(a)c")
  one := regex.find(captured.value, "ac")
  require(one.ok && !one.captures[0].ok && one.captures[1].ok && one.captures[1].end == 1, "captures")
  two := regex.find(captured.value, "zz")
  require(two.ok && !two.value.ok && !two.captures[0].ok && !two.captures[1].ok, "capture clear")
  backing: [32768]u8
  for i in 0..#len(backing) { backing[i] = 255 }
  fixed := mem.arena_from_buffer(backing[..])
  fixed_program := regex.compile(&fixed, "(a)*")
  require(fixed_program.ok && regex.find(fixed_program.value, "aaa").captures[0].start == 2, "dirty backing zero initialization")
  long_program := regex.compile(&arena, "^(a)*$")
  long_text := mem.push_array(u8, &arena, 100000)
  for i in 0..#len(long_text) { long_text[i] = 'a' }
  long_result := regex.find(long_program.value, long_text)
  require(long_result.value.ok && long_result.value.end == 100000 && long_result.captures[0].start == 99999, "long Thompson repetition")
  iter_program := regex.compile(&arena, "(a+)")
  iter := regex.iterator(iter_program.value, "aa baa")
  x := regex.next(&iter)
  require(x.value.start == 0 && x.value.end == 2, "iterator first")
  y := regex.next(&iter)
  require(y.value.start == 4 && y.captures[0].start == 4, "iterator capture offset")
  anchored := regex.compile(&arena, "^a")
  anchored_iter := regex.iterator(anchored.value, "aa")
  require(regex.next(&anchored_iter).value.ok && !regex.next(&anchored_iter).value.ok, "iterator absolute anchors")
''' + '\n'.join(checks) + '\n}\n'
with tempfile.TemporaryDirectory(prefix='dyn-regex-arena-') as temporary:
    work = Path(temporary)
    main = work / 'main'
    main.mkdir()
    (main / 'main.dyn').write_text(source)
    small = work / 'capacity'
    small.mkdir()
    (small / 'main.dyn').write_text('''use "std/mem" mem
use "std/text/regex" regex
fn main() {
  backing: [8]u8
  arena := mem.arena_from_buffer(backing[..])
  _ = regex.compile(&arena, "abc")
}
''')
    for mode in ('--debug', '--release'):
        for project, success in ((main, True), (small, False)):
            output = work / 'out'
            subprocess.run([str(DYN), 'build', str(project), '--no-cache', '--quiet', '--output', str(output), mode], cwd=ROOT, check=True, timeout=120)
            result = subprocess.run([str(output)], capture_output=True, timeout=30)
            assert (result.returncode == 0) == success, (mode, project.name, result.stdout, result.stderr)
print(f'PASS regex arena ownership, invalid offsets, capacity panic, zero init, reuse, captures, iterator; {len(cases)} Python-re cases (debug/release)')
