#!/usr/bin/env python3
"""Concrete vector contracts against independent, rounded Python references.

DYN selects the compiler; VECTOR_RANDOM sets deterministic cases per dimension.
A separately compiled C input table makes every operand runtime opaque in both
build modes. No expected values are computed by the Dyn vector implementation.
"""
import math
import os
from pathlib import Path
import random
import shlex
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
COUNT = int(os.environ.get('VECTOR_RANDOM', '40'))
assert COUNT >= 0
rng = random.Random(0x564543)


def f32(x):
    try:
        return struct.unpack('<f', struct.pack('<f', x))[0]
    except OverflowError:
        return math.copysign(math.inf, x)


def bits(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def add(a, b):
    return f32(a + b)


def sub(a, b):
    return f32(a - b)


def mul(a, b):
    return f32(a * b)


def dot(a, b):
    products = [mul(x, y) for x, y in zip(a, b)]
    result = products[0]
    for x in products[1:]:
        result = add(result, x)
    return result


def divide(x, y):
    if math.isinf(x) and math.isinf(y):
        return math.nan
    return f32(x / y)


def magnitude(a):
    # Python floats hold each f32 square exactly; accumulate and sqrt in f64.
    return math.sqrt(sum(x * x for x in a))


words = []
functions = []
checks = 0
unit_checks = 0


def operand(x, integer=False):
    index = len(words)
    words.append((x & 0xffffffff) if integer else bits(x))
    return f'#bitcast({"i32" if integer else "f32"}, input({index}))'


def check(expr, expected, integer=False):
    global checks
    checks += 1
    if integer:
        return f'  if {expr} != {expected} {{ #panic("check {checks}") }}'
    # Compare exact f32 results, including signed zero; NaN payload is unspecified.
    test = f'!math.is_nan({expr})' if math.isnan(expected) else f'#bitcast(u32, {expr}) != {bits(expected)}'
    return f'  if {test} {{ #panic("check {checks}") }}'


for n in (2, 3, 4):
    fields = 'xyzw'[:n]
    cases = [([0.0]*n, [1.0]*n, 0.5),
             ([3.0, 4.0]+[0.0]*(n-2), [1.0, -2.0]+[2.0]*(n-2), 0.25),
             ([1e30]*n, [-1e30]*n, 2.0),
             ([1e-30]*n, [-0.0]*n, -0.5),
             ([math.inf]+[1.0]*(n-1), [-math.inf]*n, 0.0),
             ([math.nan]+[-0.0]*(n-1), [2.0]*n, 1.0),
             ([-0.0]*n, [0.0]*n, 0.0),
             ([16777216.0, 1.0]+[1.0]*(n-2), [1.0]*n, 0.5),
             ([1.0]*n, [math.nan]*n, 0.5),
             ([f32(2**-149)]*n, [1.0]*n, 0.5)]
    if n == 3:
        cases += [([1.0,0.0,0.0],[0.0,1.0,0.0],0.5),
                  ([0.0,1.0,0.0],[1.0,0.0,0.0],0.5)]
    cases += [([f32(rng.uniform(-100, 100)) for _ in fields],
               [f32(rng.uniform(-100, 100)) for _ in fields],
               f32(rng.uniform(-2, 2))) for _ in range(COUNT)]
    maximum = f32(float.fromhex('0x1.fffffep+127'))
    minimum = f32(2**-149)
    cases += [(values, [0.0]*n, 0.5) for values in (
        [maximum]*n,
        [-maximum]+[maximum]*(n-1),
        [minimum]+[0.0]*(n-1),
        [-minimum]*n,
        [maximum, minimum]+[-1.0]*(n-2),
        [1e30]+[0.0]*(n-1),
        [1e-30]+[0.0]*(n-1),
    )]
    for a, b, t in cases:
        a, b, t = list(map(f32, a)), list(map(f32, b)), f32(t)
        name = f'test_{len(functions)}'
        lines = [f'fn {name}() {{']
        for label, values in [('a', a), ('b', b)]:
            lines.append(f'  {label} := math.Vec{n}{{ '+', '.join(f'{c}: {operand(v)}' for c, v in zip(fields, values))+' }')
        lines.append(f'  t := {operand(t)}')
        expected = {'add': [add(x,y) for x,y in zip(a,b)],
                    'sub': [sub(x,y) for x,y in zip(a,b)],
                    'mul': [mul(x,y) for x,y in zip(a,b)],
                    'scale': [mul(x,t) for x in a],
                    'min': [y if y<x else x for x,y in zip(a,b)],
                    'max': [y if x<y else x for x,y in zip(a,b)],
                    'lerp': [add(x,mul(sub(y,x),t)) for x,y in zip(a,b)]}
        wide_length = magnitude(a)
        length = f32(wide_length)
        expected['normalize'] = [0.0]*n if wide_length == 0 else [divide(x,wide_length) for x in a]
        if n == 3:
            expected['cross'] = [sub(mul(a[1],b[2]),mul(a[2],b[1])),
                                 sub(mul(a[2],b[0]),mul(a[0],b[2])),
                                 sub(mul(a[0],b[1]),mul(a[1],b[0]))]
        for op, values in expected.items():
            args = 'a, t' if op == 'scale' else 'a' if op == 'normalize' else 'a, b, t' if op == 'lerp' else 'a, b'
            lines.append(f'  r_{op} := math.vec{n}_{op}({args})')
            lines += [check(f'r_{op}.{c}', v) for c,v in zip(fields,values)]
        lines += [check(f'math.vec{n}_dot(a,b)',dot(a,b)), check(f'math.vec{n}_length(a)',length)]
        # Geometric property independent of the formula/bit oracle.
        if all(math.isfinite(x) for x in a) and any(x != 0 for x in a):
            unit_checks += 1
            lines.append(f'  unit_length := math.vec{n}_length(r_normalize)')
            lines.append('  if !math.is_finite(unit_length) || unit_length < 0.999999 || unit_length > 1.000001 { #panic("unit length") }')
        if n == 3 and all(math.isfinite(x) and abs(x) < 101 for x in a+b):
            lines.append('  orthogonal := math.vec3_dot(r_cross,a)')
            lines.append('  if orthogonal < -0.25 || orthogonal > 0.25 { #panic("cross orthogonality") }')
        lines.append('}')
        functions.append('\n'.join(lines))

# Integer reference uses Python's unbounded arithmetic, not wrapping.
for a,b in [((0,0),(0,0)), ((3,4),(-2,7)), ((2147483647,-2147483648),(0,0))] + [
        (tuple(rng.randint(-1000,1000) for _ in range(2)),tuple(rng.randint(-1000,1000) for _ in range(2))) for _ in range(COUNT)]:
    lines = [f'fn test_{len(functions)}() {{']
    for label, values in [('a',a),('b',b)]:
        lines.append(f'  {label} := math.Vec2i{{ x: {operand(values[0],True)}, y: {operand(values[1],True)} }}')
    for op, values in [('add',[x+y for x,y in zip(a,b)]),('sub',[x-y for x,y in zip(a,b)]),
                       ('mul',[x*y for x,y in zip(a,b)]),('scale',[x*b[0] for x in a]),
                       ('min',list(map(min,a,b))),('max',list(map(max,a,b)))]:
        lines.append(f'  r_{op} := math.vec2i_{op}(a, {"b.x" if op == "scale" else "b"})')
        lines += [check(f'r_{op}.{c}',v,True) for c,v in zip('xy',values)]
    lines.append(check('math.vec2i_dot(a,b)',sum(x*y for x,y in zip(a,b)),True))
    af,bf = list(map(f32,a)),list(map(f32,b))
    wide_length = magnitude(af)
    length = f32(wide_length)
    lines.append(check('math.vec2i_length(a)',length))
    lines.append('  norm := math.vec2i_normalize(a)')
    lines.append('  mid := math.vec2i_lerp(a,b,0.5)')
    for c,x,y in zip('xy',af,bf):
        lines.append(check(f'norm.{c}',0.0 if wide_length == 0 else divide(x,wide_length)))
        lines.append(check(f'mid.{c}',add(x,mul(sub(y,x),0.5))))
    if any(x != 0 for x in a):
        unit_checks += 1
        lines.append('  unit_length := math.vec2_length(norm)')
        lines.append('  if !math.is_finite(unit_length) || unit_length < 0.999999 || unit_length > 1.000001 { #panic("integer unit length") }')
    lines.append('}')
    functions.append('\n'.join(lines))

with tempfile.TemporaryDirectory(prefix='dyn-math-vector-') as tmp:
    work = Path(tmp)
    source = work/'source'
    source.mkdir()
    module = source/'math'
    module.mkdir()
    # Snapshot current module siblings without modifying concurrently owned files.
    for filename in ('math.dyn','float.dyn','vector.dyn'):
        (module/filename).write_text((ROOT/'std/math'/filename).read_text())
    header = 'extern fn input(index: u32) u32\n'
    header = 'use "math"\n' + header
    (work/'input.c').write_text('#include <stdint.h>\nstatic const uint32_t data[] = {' + ','.join(map(str,words)) + '};\nuint32_t input(uint32_t i) { return data[i]; }\n')
    subprocess.run([*shlex.split(os.environ.get('CC','cc')), '-shared','-fPIC',str(work/'input.c'),'-o',str(work/'input.so')],check=True)
    normal = header+'\n'.join(functions)+'\nfn main() {\n  zero: math.Vec4 = .{}\n  if math.vec4_length(zero) != 0.0 { #panic("zero initialization") }\n'+'\n'.join(f'  test_{i}()' for i in range(len(functions)))+'\n}\n'
    panics = [
        'math.vec2i_add(a,b)', 'math.vec2i_sub(math.Vec2i{ x: -a.x - 1 },b)',
        'math.vec2i_mul(a,b)', 'math.vec2i_scale(a,2)',
        'math.vec2i_dot(a,b)',
        'math.vec2i_add(math.Vec2i{ y: a.x }, math.Vec2i{ y: 1 })',
        'math.vec2i_sub(math.Vec2i{ y: -a.x - 1 }, math.Vec2i{ y: 1 })',
        'math.vec2i_scale(math.Vec2i{ y: -a.x - 1 }, -1)',
        # Dot sum overflow even though individual products fit.
        'math.vec2i_dot(math.Vec2i{ x: a.x, y: 1 }, math.Vec2i{ x: 1, y: 1 })',
        'math.vec2i_mul(math.Vec2i{ x: -a.x - 1 }, math.Vec2i{ x: -1 })',
    ]
    for mode in ('debug','release'):
        for case, expression in enumerate([None]+panics):
            program = normal if expression is None else header + 'fn main() {\n a := math.Vec2i{ x: #bitcast(i32,input(0)), y: 0 }\n b := math.Vec2i{ x: 2, y: 0 }\n _ = '+expression+'\n}'
            # First table entry is zero; use an opaque boundary input at its own index.
            if expression is not None:
                program = program.replace('input(0)',f'input({len(words)})')
                (work/'input.c').write_text('#include <stdint.h>\nuint32_t input(uint32_t i) { return 2147483647U; }\n')
                subprocess.run([*shlex.split(os.environ.get('CC','cc')),'-shared','-fPIC',str(work/'input.c'),'-o',str(work/'panic.so')],check=True)
            (source/'main.dyn').write_text(program)
            library = work/('input.so' if expression is None else 'panic.so')
            subprocess.run([DYN,'build',str(source),'--no-cache','--quiet',f'--{mode}','--link',str(library),'--output',str(work/'test')],check=True,timeout=120)
            result = subprocess.run([str(work/'test')],capture_output=True,timeout=60)
            if expression is None:
                assert result.returncode == 0, (mode,result.stdout,result.stderr)
            else:
                assert result.returncode != 0 and b'overflow' in result.stderr.lower(), (mode,expression,result.returncode,result.stderr)
        print(f'PASS {mode}: {checks} reference checks, {unit_checks} unit-length properties, {len(panics)} overflow panics',flush=True)
