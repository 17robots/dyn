#!/usr/bin/env python3
"""Loop leaf inlining preserves captures, target addresses and runtime checks."""
import os
from pathlib import Path
import re
import subprocess
import struct
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())


def run(*args, success=True, env=None):
    result = subprocess.run([str(x) for x in args], cwd=ROOT, text=True,
                            capture_output=True, timeout=30, env=env)
    assert (result.returncode == 0) == success, (args, result.stdout, result.stderr)
    return result


with tempfile.TemporaryDirectory(prefix='dyn-leaf-inline-') as directory:
    root = Path(directory)
    module = root / 'module'
    module.mkdir()
    (module / 'main.dyn').write_text('''
struct Pair { x: i64, y: i64 }
state: i64 = 0
fn next() i64 { state += 1 return state }
fn pair(a: i64, b: i64) Pair { return Pair{x: a + b, y: a - b} }
fn change(target: **i64, replacement: *i64) i64 { target.* = replacement return 7 }
fn identity(value: i64) i64 { return value }
fn main() {
  constant := Pair{x: 41, y: 23}
  if constant.x + constant.y != 64 { #panic("constant aggregate") }
  total: i64 = 0
  for i in 0..3 {
    value := pair(next(), next())
    total += value.x + value.y
  }
  if total != 18 || state != 6 { #panic("argument captures") }
  points: [3]Pair = []
  for *p in points { p.* = pair(12, 5) }
  for p in points { if p.x != 17 || p.y != 7 { #panic("aggregate leaf") } }
  old: i64 = 1
  other: i64 = 2
  pointer := &old
  for i in 0..1 { pointer.* = identity(change(&pointer, &other)) }
  if old != 7 || other != 2 || pointer != &other { #panic("target evaluation order") }
}
''')
    literal_sizes = []
    for level in (1, 2, 3):
        output = root / f'leaf-{level}'
        result = run(DYN, 'build', module, '--release', '--opt-level', level,
                     '--no-cache', '--opt-remarks', '--output', output)
        run(output)
        if level in (1, 2):
            obj = root / f'literals-{level}'
            run(DYN, 'build', module, '--release', '--opt-level', level,
                '--no-cache', '--emit-object', '--no-link', '--output', obj)
            data = obj.with_suffix('.o').read_bytes()
            if data[:6] == b'\x7fELF\x02\x01':
                header = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
                sections = [struct.unpack_from('<IIQQQQIIQQ', data, header[6] + i * header[11])
                            for i in range(header[12])]
                names = sections[header[13]]
                strings = data[names[4]:names[4] + names[5]]
                literal_sizes.append(next(section[5] for section in sections
                                          if strings[section[0]:].split(b'\0', 1)[0] == b'.data.rel.ro'))
        if level == 2:
            count = re.search(r'(\d+) direct calls inlined', result.stderr)
            assert count and int(count.group(1)) >= 2, result.stderr
    if literal_sizes:
        assert len(literal_sizes) == 2 and literal_sizes[1] <= literal_sizes[0], literal_sizes
    (module / 'main.dyn').write_text('''
use "std/io"
fn add(a: i8, b: i8) i8 { return a + b }
fn main() {
  defer { _ = io.println(io.stdout(), "cleanup") }
  for i in 0..1 { value := add(127, 1) _ = value }
}
''')
    for level in (2, 3):
        output = root / f'overflow-{level}'
        run(DYN, 'build', module, '--release', '--opt-level', level,
            '--no-cache', '--output', output)
        result = run(output, success=False)
        assert result.stdout.splitlines() == ['cleanup'], result.stdout
        assert 'overflow' in result.stderr, result.stderr
    # Target checks precede both argument checks and checks in the leaf body.
    for pointer, message in (('nil', 'null'), ('#cast(*i64) #cast(usize) 1', 'align')):
        (module / 'main.dyn').write_text(f'''
fn add(a: i64, b: i64) i64 {{ return a + b }}
fn main() {{
  pointer: *i64 = {pointer}
  for i in 0..1 {{ pointer.* = add(9223372036854775807, 1) }}
}}
''')
        for level in (1, 2, 3):
            output = root / f'target-check-{message}-{level}'
            run(DYN, 'build', module, '--release', '--opt-level', level,
                '--no-cache', '--output', output)
            result = run(output, success=False)
            assert message in result.stderr.lower(), result.stderr
            assert 'overflow' not in result.stderr.lower(), result.stderr
    # Caller and multiple inlined callees can share one check kind without
    # sharing diagnostic origins. Exercise SSA and the fallback tree emitter.
    for failure, origin in ((0, 'leaf_add'), (1, 'leaf_other'), (2, 'main')):
        (module / 'main.dyn').write_text(f'''
limit: i64 = 9223372036854775807
failure: i64 = {failure}
fn leaf_add(a: i64, b: i64) i64 {{ return a + b }}
fn leaf_other(a: i64, b: i64) i64 {{ return a + b }}
fn main() {{
  for i in 0..1 {{
    first: i64 = 0 second: i64 = 0 third: i64 = 0
    if failure != 0 {{ first = 1 }}
    if failure != 1 {{ second = 1 }}
    if failure == 2 {{ third = 1 }}
    a := leaf_add(limit - first, 1)
    b := leaf_other(limit - second, 1)
    value := limit + third
    if a != limit || b != limit || value != limit {{ #panic("unexpected value") }}
  }}
}}
''')
        expected = f'runtime check failed (overflow.ok) in {origin}\n'
        for tree in (False, True):
            environment = dict(os.environ, DYN_NO_SSA='1' if tree else '0')
            for level in (1, 2, 3):
                output = root / f'origin-{failure}-{tree}-{level}'
                run(DYN, 'build', module, '--release', '--opt-level', level,
                    '--no-cache', '--output', output, env=environment)
                result = run(output, success=False)
                assert result.stderr == expected, (level, tree, result.stderr, expected)
    # Nested expansion and compound assignments retain the original callee.
    # Struct defaults still execute before explicit field initialization.
    for source, origin in (('''
limit: i64 = 9223372036854775807
fn leaf_add(a: i64, b: i64) i64 { return a + b }
fn nested(a: i64) i64 { return leaf_add(a, 1) }
fn main() { for i in 0..1 { value := nested(limit) _ = value } }
''', 'leaf_add'), ('''
limit: i64 = 9223372036854775807
struct Defaulted { value: i64 = 5 + 7 }
fn leaf_default(a: i64) Defaulted { return Defaulted{value: a + 1} }
fn main() { for i in 0..1 { value := leaf_default(limit) _ = value } }
''', 'leaf_default'), ('''
limit: i64 = 9223372036854775807
fn leaf_compound(a: i64) i64 { result := a result += 1 return result }
fn main() { for i in 0..1 { value := leaf_compound(limit) _ = value } }
''', 'leaf_compound')):
        (module / 'main.dyn').write_text(source)
        expected = f'runtime check failed (overflow.ok) in {origin}\n'
        for tree in (False, True):
            environment = dict(os.environ, DYN_NO_SSA='1' if tree else '0')
            for level in (1, 2, 3):
                output = root / f'origin-extra-{origin}-{tree}-{level}'
                run(DYN, 'build', module, '--release', '--opt-level', level,
                    '--no-cache', '--output', output, env=environment)
                result = run(output, success=False)
                assert result.stderr == expected, (level, tree, result.stderr, expected)
    # A caller cleanup that itself fails must not inherit the failed callee's
    # origin while emitting the cleanup ladder.
    (module/'main.dyn').write_text("""
limit: i64 = 9223372036854775807
fn leaf_add(a: i64) i64 { return a + 1 }
fn main() {
  defer { limit += 1 }
  for i in 0..1 { value := leaf_add(limit) _ = value }
}
""")
    for tree in (False, True):
        outputs=[]
        environment=dict(os.environ,DYN_NO_SSA='1' if tree else '0')
        for level in (1,2,3):
            output=root/f'cleanup-origin-{tree}-{level}'
            run(DYN,'build',module,'--release','--opt-level',level,'--no-cache','--output',output,env=environment)
            result=run(output,success=False)
            outputs.append((result.returncode,result.stdout,result.stderr))
        assert len(set(outputs))==1,outputs
print('PASS loop leaf capture order, aggregate returns, target aliases and checked overflow cleanup')
