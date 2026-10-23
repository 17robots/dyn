#!/usr/bin/env python3
"""Independent double-precision Python oracles; opaque C runtime inputs.

DYN/CC select compilers. MATRIX_RANDOM (default 32) controls seeded samples.
Both debug and release run. Well-conditioned matrices use abs/relative 3e-5;
rotations/projections use 5e-5. These sampled acceptance tolerances are not
condition-independent error bounds. No numpy or implementation-generated oracle.
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
COUNT = int(os.environ.get('MATRIX_RANDOM', '32'))
assert 0 <= COUNT <= 1000
rng = random.Random(0x4D4154)
words, functions = [], []
checks = 0


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def operand(x):
    index = len(words)
    words.append(struct.unpack('<I', struct.pack('<f', x))[0])
    return f'#bitcast(f32,input({index}))'


def vec(v):
    return f'math.Vec{len(v)}{{ ' + ', '.join(f'{c}: {operand(x)}' for c, x in zip('xyzw', v)) + ' }'


def quat(q):
    return 'math.Quat{ ' + ', '.join(f'{c}: {operand(x)}' for c, x in zip('xyzw', q)) + ' }'


def matrix(a):
    return f'math.Mat{len(a)}{{ ' + ', '.join(f'c{j}: {vec([row[j] for row in a])}' for j in range(len(a))) + ' }'


def check(expr, value, tol=3e-5):
    global checks
    checks += 1
    budget = tol * max(1, abs(value))
    return f'if !math.is_finite({expr}) || math.abs(#cast(f64,{expr}) - ({value:.17e})) > {budget:.17e} {{ #panic("check {checks}: {expr}") }}'


def flag(expr, expected=True):
    global checks
    checks += 1
    return f'if {"!" if expected else ""}{expr} {{ #panic("flag {checks}: {expr}") }}'


def cm(expr, a, tol=3e-5):
    return [check(f'{expr}.c{j}.{c}', a[i][j], tol) for i, c in enumerate('xyzw'[:len(a)]) for j in range(len(a))]


def cv(expr, v, tol=5e-5):
    return [check(f'{expr}.{c}', x, tol) for c, x in zip('xyzw', v)]


def emit(lines):
    functions.append('fn test_' + str(len(functions)) + '() {\n' + '\n'.join(lines) + '\n}')


def ident(n):
    return [[float(i == j) for j in range(n)] for i in range(n)]


def mm(a, b):
    return [[sum(x*y for x, y in zip(row, col)) for col in zip(*b)] for row in a]


def mv(a, v):
    return [sum(x*y for x, y in zip(row, v)) for row in a]


def inverse(a):
    # Independent solve via recursive determinants/cofactors, not elimination.
    def det(m):
        if len(m) == 1:
            return m[0][0]
        return sum((-1)**j * m[0][j] * det([row[:j]+row[j+1:] for row in m[1:]]) for j in range(len(m)))
    d = det(a)
    n = len(a)
    return [[(-1)**(i+j)*det([row[:i]+row[i+1:] for k, row in enumerate(a) if k != j])/d for j in range(n)] for i in range(n)]


for n in (3, 4):
    cases = [ident(n), [list(row) for row in zip(*reversed(ident(n)))]]
    cases += [[[f32(rng.uniform(-1, 1)) + (4 if i == j else 0) for j in range(n)] for i in range(n)] for _ in range(COUNT)]
    cases += [[[1e-30 if i == j else 0 for j in range(n)] for i in range(n)]]
    near_singular = ident(n)
    near_singular[0][0], near_singular[0][1] = 1, 1
    near_singular[1][0], near_singular[1][1] = 1, f32(1+2**-20)
    cases.append(near_singular)
    for a in cases:
        a = [list(map(f32, row)) for row in a]
        b = [[f32(rng.uniform(-2, 2)) for _ in range(n)] for _ in range(n)]
        v = [f32(rng.uniform(-2, 2)) for _ in range(n)]
        lines = [f'a := {matrix(a)}', f'b := {matrix(b)}', f'v := {vec(v)}',
                 f'p := math.mat{n}_mul(a,b)', f't := math.mat{n}_transpose(a)',
                 f'r := math.mat{n}_inverse(a)', flag('r.ok'),
                 f'u := math.mat{n}_mul(a,r.value)', f'w := math.mat{n}_mul_vec{n}(a,v)']
        lines += cm('p', mm(a, b)) + cm('t', list(zip(*a)), 0) + cm('r.value', inverse(a)) + cm('u', ident(n)) + cv('w', mv(a, v))
        emit(lines)
    # Exact dependent rows, nonfinite input, unrepresentable inverse.
    singular = ident(n)
    singular[-1] = singular[0][:]
    for a in [singular, [[0.0]*n for _ in range(n)], [[math.inf if i == j == 0 else float(i == j) for j in range(n)] for i in range(n)], [[math.nan if i == j == 0 else float(i == j) for j in range(n)] for i in range(n)], [[2**-149 if i == j else 0 for j in range(n)] for i in range(n)]]:
        emit([f'a := {matrix(a)}', f'r := math.mat{n}_inverse(a)', flag('r.ok', False)] + cm('r.value', [[0]*n for _ in range(n)], 0))
    emit([f'a := math.mat{n}_identity()'] + cm('a', ident(n), 0))

# Known noncommuting 2D and 3D transforms, independently derived endpoints.
for n in (3, 4):
    v = [2, 3] if n == 3 else [2, 3, 4]
    sc = [2, -3] if n == 3 else [2, -3, 4]
    p = [1, 2, 1] if n == 3 else [1, 2, 3, 1]
    angle = f32(math.pi/2)
    rotation = f'math.mat3_rotate({operand(angle)})' if n == 3 else f'math.mat4_rotate({vec([0, 0, 3])},{operand(angle)})'
    # +Z rotation: (x,y) -> (-y,x).
    s = ident(n)
    for i, x in enumerate(sc):
        s[i][i] = x
    t = ident(n)
    for i, x in enumerate(v):
        t[i][-1] = x
    r = ident(n)
    r[0][0], r[0][1], r[1][0], r[1][1] = math.cos(angle), -math.sin(angle), math.sin(angle), math.cos(angle)
    lines = [f't := math.mat{n}_translate({vec(v)})', f's := math.mat{n}_scale({vec(sc)})', f'r := {rotation}', flag('t.ok'), flag('s.ok'), flag('r.ok'), f'p := {vec(p)}', f'a := math.mat{n}_mul(t.value,math.mat{n}_mul(r.value,s.value))', f'b := math.mat{n}_mul(s.value,math.mat{n}_mul(r.value,t.value))', f'x := math.mat{n}_mul_vec{n}(a,p)', f'y := math.mat{n}_mul_vec{n}(b,p)']
    emit(lines + cv('x', mv(mm(t, mm(r, s)), p)) + cv('y', mv(mm(s, mm(r, t)), p)))

# Quaternion oracle uses Rodrigues' axis-angle formula, independent of quat_to_mat3.
def rotation(v):
    angle = math.sqrt(sum(x*x for x in v))
    if angle == 0:
        return ident(3)
    x, y, z = [t/angle for t in v]
    k = [[0, -z, y], [z, 0, -x], [-y, x, 0]]
    k2 = mm(k, k)
    return [[float(i == j)+math.sin(angle)*k[i][j]+(1-math.cos(angle))*k2[i][j] for j in range(3)] for i in range(3)]


for v in [[0, 0, 0], [math.pi/2, 0, 0], [0, math.pi/2, 0], [0, 0, math.pi/2], [1e-30, 0, 0]] + [[rng.uniform(-1, 1) for _ in range(3)] for _ in range(COUNT)]:
    v = list(map(f32, v))
    b = [f32(rng.uniform(-1, 1)) for _ in range(3)]
    a_ref, b_ref = rotation(v), rotation(b)
    lines = [f'a := math.quat_from_rotation_vector({vec(v)})', f'b := math.quat_from_rotation_vector({vec(b)})', flag('a.ok'), flag('b.ok'), 'm := math.quat_to_mat3(a.value)', flag('m.ok'), 'q := math.quat_mul(a.value,b.value)', 'p := math.quat_to_mat3(q)', flag('p.ok'), 'rv := math.quat_to_rotation_vector(a.value)', flag('rv.ok')]
    lines += cm('m.value', a_ref, 5e-5) + cm('p.value', mm(a_ref, b_ref), 5e-5) + cv('rv.value', v)
    # Each matrix column is a rotated basis vector, covering all three axes.
    emit(lines)

for q in [[1, 2, 3, 4], [1e30, -2e30, 3e30, -4e30], [1e-30, 0, 0, 1e-30], [0, 0, 0, -2], [2**-149, 0, 0, 0]]:
    q = list(map(f32, q))
    norm = math.sqrt(sum(x*x for x in q))
    normalized = [x/norm for x in q]
    lines = [f'q := {quat(q)}', 'n := math.quat_normalize(q)', flag('n.ok')] + cv('n.value', normalized)
    lines += ['rv := math.quat_to_rotation_vector(q)', flag('rv.ok'), 'back := math.quat_from_rotation_vector(rv.value)', flag('back.ok'), 'm := math.quat_to_mat3(q)', 'b := math.quat_to_mat3(back.value)', flag('m.ok'), flag('b.ok')]
    # Roundtrip compares rotations, allowing q and -q.
    lines += [check(f'b.value.c{j}.{c} - m.value.c{j}.{c}', 0, 5e-5) for j in range(3) for c in 'xyz']
    emit(lines)

# P2 regressions are additive: preserve the original 8522 checks / 293 cases
# at MATRIX_RANDOM=32. No unit-sized absolute floor for tiny components.
def relative_check(expr, value, relative=3e-6, ulps=4):
    rounded = abs(f32(value))
    bits = struct.unpack('<I', struct.pack('<f', rounded))[0]
    next_value = struct.unpack('<f', struct.pack('<I', bits+1))[0]
    budget = max(relative*abs(value), ulps*(next_value-rounded))
    return check(expr, value, budget/max(1, abs(value)))


control_checks = {}
for scale in (1e-30, 1e-8):
    v = list(map(f32, [scale, -2*scale, 3*scale]))
    angle = math.sqrt(sum(x*x for x in v))
    expected_q = [x*math.sin(angle/2)/angle for x in v] + [math.cos(angle/2)]
    # Feed the reverse conversion an independent Python quaternion, not a's output.
    input_q = list(map(f32, expected_q))
    vector_norm = math.sqrt(sum(x*x for x in input_q[:3]))
    expected_v = [x/vector_norm * (2*math.atan2(vector_norm, input_q[3])) for x in input_q[:3]]
    lines = [f'a := math.quat_from_rotation_vector({vec(v)})', flag('a.ok')]
    control_checks.setdefault('smallangle-identity', []).append((len(functions), checks+1))
    lines += [relative_check(f'a.value.{c}', x) for c, x in zip('xyzw', expected_q)]
    lines += [f'r := math.quat_to_rotation_vector({quat(input_q)})', flag('r.ok')]
    control_checks.setdefault('smallangle-zero', []).append((len(functions), checks+1))
    lines += [relative_check(f'r.value.{c}', x) for c, x in zip('xyz', expected_v)]
    emit(lines)

# Negative w must select the signed shortest rotation, including just beyond pi
# and just below 2*pi. A matrix-equivalence assertion cannot distinguish these.
for angle in (math.pi+1e-4, 2*math.pi-1e-4):
    axis = [2/7, -3/7, 6/7]
    q = list(map(f32, [x*math.sin(angle/2) for x in axis]+[math.cos(angle/2)]))
    assert q[3] < 0
    vector_norm = math.sqrt(sum(x*x for x in q[:3]))
    shortest = 2*math.acos(abs(q[3])/math.sqrt(sum(x*x for x in q)))
    expected = [-x/vector_norm*shortest for x in q[:3]]
    lines = [f'r := math.quat_to_rotation_vector({quat(q)})', flag('r.ok')]
    control_checks.setdefault('negative-w-correction', []).append((len(functions), checks+1))
    lines += [relative_check(f'r.value.{c}', x) for c, x in zip('xyz', expected)]
    lines += [flag('('+' + '.join(f'#cast(f64,r.value.{c}) * ({x:.17e})' for c, x in zip('xyz', axis))+' < 0.0)')]
    lines += [relative_check(' + '.join(f'#cast(f64,r.value.{c}) * #cast(f64,r.value.{c})' for c in 'xyz'), shortest*shortest, relative=6e-6)]
    emit(lines)

# Axis-angle Mat4 against Rodrigues, with nonunit/huge/subnormal axes.
for axis in [[0,0,7], [1e30,-2e30,3e30], [2**-149,0,0]] + [[rng.uniform(-3,3) for _ in range(3)] for _ in range(COUNT)]:
    axis = list(map(f32,axis))
    angle = f32(rng.uniform(-3,3))
    length = math.sqrt(sum(x*x for x in axis))
    ref3 = rotation([x/length*angle for x in axis])
    ref = [row+[0] for row in ref3]+[[0,0,0,1]]
    emit([f'm := math.mat4_rotate({vec(axis)},{operand(angle)})',flag('m.ok')] + cm('m.value',ref,5e-5))

# Projection oracle verifies actual clip-coordinate division at near/far/corners.
for _ in range(COUNT+1):
    fov, aspect, near, far = map(f32, [rng.uniform(.4, 2.5), rng.uniform(.5, 3), rng.uniform(.1, 2), rng.uniform(5, 100)])
    y = 1/math.tan(fov/2)
    ref = [[y/aspect, 0, 0, 0], [0, y, 0, 0], [0, 0, -(far+near)/(far-near), -2*far*near/(far-near)], [0, 0, -1, 0]]
    lines = [f'm := math.mat4_perspective({",".join(operand(x) for x in [fov, aspect, near, far])})', flag('m.ok')] + cm('m.value', ref, 5e-5)
    for i, depth in enumerate([near, far]):
        lines += [f'p{i} := math.mat4_mul_vec4(m.value,{vec([depth*aspect/y, depth/y, -depth, 1])})', check(f'p{i}.z/p{i}.w', -1 if i == 0 else 1, 5e-5), check(f'p{i}.x/p{i}.w', 1, 5e-5), check(f'p{i}.y/p{i}.w', 1, 5e-5)]
    emit(lines)
    l, r, b, t = map(f32, [-rng.uniform(1, 4), rng.uniform(1, 5), -rng.uniform(1, 3), rng.uniform(1, 6)])
    ref = [[2/(r-l), 0, 0, -(r+l)/(r-l)], [0, 2/(t-b), 0, -(t+b)/(t-b)], [0, 0, -2/(far-near), -(far+near)/(far-near)], [0, 0, 0, 1]]
    lines = [f'm := math.mat4_orthographic({",".join(operand(x) for x in [l,r,b,t,near,far])})', flag('m.ok')] + cm('m.value', ref, 5e-5)
    for i, (point, expected) in enumerate([([l,b,-near,1], [-1,-1,-1,1]), ([r,t,-far,1], [1,1,1,1])]):
        lines += [f'p{i} := math.mat4_mul_vec4(m.value,{vec(point)})'] + cv(f'p{i}', expected)
    emit(lines)


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def unit(a):
    length = math.sqrt(sum(x*x for x in a))
    return [x/length for x in a]


for eye, target, up in [([0,0,5], [0,0,0], [0,1,0]), ([2,3,4], [-1,1,2], [0,2,1])] + [([rng.uniform(-4,4) for _ in range(3)], [rng.uniform(-4,4) for _ in range(3)], [0,1,0]) for _ in range(COUNT)]:
    eye, target, up = [list(map(f32, v)) for v in [eye,target,up]]
    f = unit([t-e for t,e in zip(target,eye)])
    r = unit(cross(f,up))
    u = cross(r,f)
    ref = [row + [-sum(x*y for x,y in zip(row,eye))] for row in [r,u,[-x for x in f]]] + [[0,0,0,1]]
    emit([f'e := {vec(eye)}', f't := {vec(target)}', f'm := math.mat4_look_at(e,t,{vec(up)})', flag('m.ok'), 'p := math.mat4_mul_vec4(m.value,math.Vec4{ x: e.x, y: e.y, z: e.z, w: 1.0 })'] + cm('m.value',ref,5e-5) + cv('p',[0,0,0,1]))

# Every rejection verifies both the flag and the specified zero value.
invalid = [
 ('mat3_rotate', [math.inf], 3), ('mat3_translate', [[math.nan,0]],3), ('mat3_scale', [[0,math.inf]],3),
 ('mat4_translate', [[0,0,math.inf]],4), ('mat4_scale', [[math.nan,0,1]],4),
 ('mat4_rotate', [[0,0,0],0],4), ('mat4_rotate', [[1,0,0],math.nan],4),
 ('mat4_look_at', [[0,0,0],[0,0,0],[0,1,0]],4),
 ('mat4_look_at', [[0,0,1],[0,0,0],[0,0,2]],4),
 ('mat4_look_at', [[math.nan,0,1],[0,0,0],[0,1,0]],4),
 ('mat4_look_at', [[0,0,1],[0,0,0],[0,0,0]],4),
]
invalid += [('mat4_perspective',args,4) for args in [[0,1,1,10],[f32(math.pi),1,1,10],[1,0,1,10],[1,1,0,10],[1,1,2,1],[1,1,1,math.inf],[1,2**-149,1,10],[2**-149,1,1,10]]]
invalid += [('mat4_orthographic',args,4) for args in [[0,0,-1,1,0,10],[-1,1,2,1,0,10],[-1,1,-1,1,-1,10],[-1,1,-1,1,2,2],[-1,math.inf,-1,1,0,10],[0,2**-149,-1,1,0,10]]]
for op, args, n in invalid:
    emit([f'r := math.{op}('+','.join(vec(a) if isinstance(a,list) else operand(a) for a in args)+')',flag('r.ok',False)]+cm('r.value',[[0]*n for _ in range(n)],0))
for q in [[0,0,0,0],[math.inf,0,0,1],[math.nan,0,0,1]]:
    emit([f'q := {quat(q)}','n := math.quat_normalize(q)',flag('n.ok',False),'m := math.quat_to_mat3(q)',flag('m.ok',False),'v := math.quat_to_rotation_vector(q)',flag('v.ok',False)] + cv('n.value',[0]*4,0) + cm('m.value',[[0]*3 for _ in range(3)],0)+cv('v.value',[0]*3,0))
emit(['r := math.quat_from_rotation_vector('+vec([math.inf,0,0])+')',flag('r.ok',False)]+cv('r.value',[0]*4,0))
# Explicit zero initialization and valid singular scale constructors.
emit(['a: math.Mat3 = .{}','b: math.Mat4 = .{}','q: math.Quat = .{}','x := math.mat3_inverse(a)','y := math.mat4_inverse(b)','z := math.quat_normalize(q)',flag('x.ok',False),flag('y.ok',False),flag('z.ok',False),'s := math.mat4_scale(math.Vec3{})',flag('s.ok'),'i := math.mat4_inverse(s.value)',flag('i.ok',False),'t := math.mat3_scale(math.Vec2{})',flag('t.ok'),'j := math.mat3_inverse(t.value)',flag('j.ok',False)])

with tempfile.TemporaryDirectory(prefix='dyn-math-matrix-') as tmp:
    work = Path(tmp)
    source = work/'source'
    module = source/'math'
    module.mkdir(parents=True)
    for filename in ('math.dyn','float.dyn','vector.dyn','matrix.dyn'):
        (module/filename).write_text((ROOT/'std/math'/filename).read_text())
    (work/'input.c').write_text('#include <stdint.h>\nstatic const uint32_t data[] = {'+','.join(map(str,words))+'};\nuint32_t input(uint32_t i) { return data[i]; }\n')
    subprocess.run([*shlex.split(os.environ.get('CC','cc')),'-shared','-fPIC',str(work/'input.c'),'-o',str(work/'input.so')],check=True)
    (source/'main.dyn').write_text('use "math"\nextern fn input(i:u32) u32\n'+'\n'.join(functions)+'\nfn main() {\n'+'\n'.join(f'test_{i}()' for i in range(len(functions)))+'\n}\n')
    failed = False
    for mode in ('debug','release'):
        result = subprocess.run([DYN,'build',str(source),'--no-cache','--quiet','--jobs','1',f'--{mode}','--link',str(work/'input.so'),'--output',str(work/'test')],timeout=180)
        if result.returncode:
            failed = True
            continue
        result = subprocess.run([str(work/'test')],capture_output=True,timeout=60)
        failed |= result.returncode != 0
        print(f'{"PASS" if result.returncode == 0 else "FAIL"} {mode}: {checks} checks, {len(functions)} cases, seed 0x4d4154',flush=True)
        if result.returncode:
            print(result.stderr.decode(),flush=True)
    # Mutate only the temporary module. Each control must compile and fail at
    # its designated new assertion, so unrelated failures cannot count as proof.
    original_matrix = (module/'matrix.dyn').read_text()
    controls = {
        'smallangle-identity': ('if angle == 0.0 {', 'if angle < 1e-6 {'),
        'smallangle-zero': ('if length == 0.0 {\n    return RotationVectorResult{ ok: true }',
                            'if length < 1e-6 {\n    return RotationVectorResult{ ok: true }'),
        'negative-w-correction': ('  if n.w < 0.0 {\n    n = Quat{ x: -n.x, y: -n.y, z: -n.z, w: -n.w }\n  }\n', ''),
    }
    for name, (before, after) in controls.items():
        assert original_matrix.count(before) == 1, (name, 'mutation anchor changed')
        (module/'matrix.dyn').write_text(original_matrix.replace(before, after, 1))
        for case_index, expected_check in control_checks[name]:
            (source/'main.dyn').write_text('use "math"\nextern fn input(i:u32) u32\n'+'\n'.join(functions)+f'\nfn main() {{ test_{case_index}() }}\n')
            for mode in ('debug', 'release'):
                build = subprocess.run([DYN,'build',str(source),'--no-cache','--quiet','--jobs','1',f'--{mode}','--link',str(work/'input.so'),'--output',str(work/'test')],timeout=180)
                if build.returncode:
                    failed = True
                    print(f'FAIL control {name} case {case_index} {mode}: compilation failed', flush=True)
                    continue
                result = subprocess.run([str(work/'test')],capture_output=True,timeout=60)
                diagnostic = (result.stdout+result.stderr).decode(errors='replace')
                expected = f'check {expected_check}:'
                caught = result.returncode != 0 and expected in diagnostic
                failed |= not caught
                print(f'{"PASS" if caught else "FAIL"} control {name} case {case_index} {mode}: expected {expected}', flush=True)
                if not caught:
                    print(diagnostic, flush=True)
    raise SystemExit(1 if failed else 0)
