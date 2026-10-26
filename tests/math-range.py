#!/usr/bin/env python3
"""Half-open range operations against independent Python interval arithmetic."""
import os
from pathlib import Path
import random
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
randomizer = random.Random(0x52414e4745)
source = ['use "std/math" m', 'const unsigned_midpoint:u64=9223372036854775807']
checks = 0
for suffix, scalar in [('u64', 'u64'), ('i64', 'i64'), ('f32', 'f32')]:
    typename = 'Rng1' + suffix
    prefix = 'rng1' + suffix
    source.append(f'fn check_{suffix}(a,b,c,d,x:{scalar}) {{')
    source.append(f'r:=m.{typename}{{min:a,max:b}}\ns:=m.{typename}{{min:c,max:d}}')
    source.append(f'if m.{prefix}_contains(r,x)!=(a<=x && x<b) {{ #panic("contains") }}')
    source.append(f'i:=m.{prefix}_intersect(r,s)\nif i.min<i.max && (!m.{prefix}_overlaps(r,s)) {{ #panic("intersection") }}')
    source.append('}')
# Bound each generated function: one giant release-optimized main is a
# compiler scaling workload, rather than a useful range-library regression.
batches = []
for suffix, scalar in [('u64', 'u64'), ('i64', 'i64'), ('f32', 'f32')]:
    typename, prefix = 'Rng1' + suffix, 'rng1' + suffix
    def literal(value):
        return f'#cast({scalar}, {value})'
    for case_index in range(120):
        if case_index % 20 == 0:
            if batches:
                source.append('}')
            name = f'range_cases_{suffix}_{case_index // 20}'
            batches.append(name)
            source.append(f'fn {name}() {{')
        a, b = sorted(randomizer.choices(range(0 if scalar == 'u64' else -100, 101), k=2))
        c, d = sorted(randomizer.choices(range(0 if scalar == 'u64' else -100, 101), k=2))
        if case_index == 0:
            a, b, c, d = 0, 1, 1, 2
        elif case_index == 1:
            a, b, c, d = 7, 7, 0, 2
        elif case_index == 2:
            a, b, c, d = 0, 2, 7, 7
        x = randomizer.randrange(0 if scalar == 'u64' else -120, 121)
        center = (a + b) / 2 if scalar == 'f32' else (a + b) // 2
        lo = max(a, c)
        hi = max(lo, min(b, d))
        source += ['if true {', f'r:=m.{typename}{{min:{literal(a)},max:{literal(b)}}}',
                   f's:=m.{typename}{{min:{literal(c)},max:{literal(d)}}}',
                   f'check_{suffix}({literal(a)},{literal(b)},{literal(c)},{literal(d)},{literal(x)})',
                   f'if m.{prefix}_center(r)!={literal(center)} || m.{prefix}_dimension(r)!={literal(b-a)} {{ #panic("center/dimension") }}',
                   f'i:=m.{prefix}_intersect(r,s)\nif i.min!={literal(lo)} || i.max!={literal(hi)} {{ #panic("intersection endpoints") }}',
                   f'u:=m.{prefix}_union(r,s)\nif u.min!={literal((c if a==b else a if c==d else min(a,c)))} || u.max!={literal((d if a==b else b if c==d else max(b,d)))} {{ #panic("union") }}',
                   f'if m.{prefix}_clamp(r,{literal(x)})!={literal(min(b,max(a,x)))} {{ #panic("clamp") }}',
                   '}']
        source.insert(len(source)-1, f'if m.{prefix}_overlaps(r,s)!={str(a<b and c<d and a<d and c<b).lower()} {{ #panic("overlap oracle") }}')
        checks += 6
source += ['}', 'fn main() {', *[f'{name}()' for name in batches]]
source += ['''
tiny:=#bitcast(f32,#cast(u32,1))
twice:=#bitcast(f32,#cast(u32,2))
if m.rng1f32_center(m.Rng1f32{min:tiny,max:tiny})!=tiny { #panic("subnormal center") }
r2:=m.Rng2f32{min:m.Vec2{x:tiny,y:-twice},max:m.Vec2{x:tiny,y:-twice}}
c2:=m.rng2f32_center(r2)
if c2.x!=tiny || c2.y!= -twice { #panic("rectangle subnormal center") }
zero:m.Rng1i64
if !m.rng1i64_empty(zero) || m.rng1i64_contains(zero,0) { #panic("zero") }
wide:=m.Rng1i64{min:m.min_value(i64),max:m.max_value(i64)}
if m.rng1i64_center(wide)!=-1 { #panic("wide midpoint") }
unsigned:=m.Rng1u64{min:0,max:m.max_value(u64)}
if m.rng1u64_center(unsigned)!=unsigned_midpoint { #panic("unsigned midpoint") }
''']
for suffix, vector in [('f32', 'Vec2'), ('i32', 'Vec2i')]:
    p = 'rng2' + suffix
    source += [f'''if true {{
r:=m.Rng2{suffix}{{min:m.{vector}{{x:-3,y:2}},max:m.{vector}{{x:5,y:8}}}}
s:=m.Rng2{suffix}{{min:m.{vector}{{x:1,y:4}},max:m.{vector}{{x:7,y:6}}}}
i:=m.{p}_intersect(r,s)
u:=m.{p}_union(r,s)
if i.min.x!=1 || i.max.x!=5 || i.min.y!=4 || i.max.y!=6 {{ #panic("rect intersection") }}
if u.min.x!= -3 || u.max.x!=7 || u.min.y!=2 || u.max.y!=8 {{ #panic("rect union") }}
c:=m.{p}_center(r)
d:=m.{p}_dimension(r)
padded:=m.{p}_pad(r,2)
if c.x!=1 || c.y!=5 || d.x!=8 || d.y!=6 || padded.min.x!= -5 || padded.max.y!=10 {{ #panic("rect dimensions") }}
if !m.{p}_contains(r,m.{vector}{{x:-3,y:2}}) || m.{p}_contains(r,m.{vector}{{x:5,y:8}}) {{ #panic("rect boundaries") }}
empty:m.Rng2{suffix}
touch:=m.Rng2{suffix}{{min:m.{vector}{{x:5,y:2}},max:m.{vector}{{x:9,y:8}}}}
if !m.{p}_overlaps(r,s) || !m.{p}_overlaps(s,r) || m.{p}_overlaps(r,touch) || m.{p}_overlaps(empty,r) || m.{p}_overlaps(r,empty) {{ #panic("rect overlap") }}
e:=m.{p}_intersect(r,touch)
if !m.{p}_empty(e) {{ #panic("rect touching") }}
ue:=m.{p}_union(empty,r)
if ue.min.x!=r.min.x || ue.max.y!=r.max.y {{ #panic("rect empty union") }}
cl:=m.{p}_clamp(r,m.{vector}{{x:-9,y:20}})
if cl.x!=r.min.x || cl.y!=r.max.y {{ #panic("rect clamp") }}

}}''']
    if suffix == 'f32':
        source[-1] = re.sub(r'(?<![\w.])(-?\d+)(?![\w.])', r'\1.0', source[-1])
source += ['}']
negative = [
    'm.rng2i32_overlaps(m.Rng2i32{},m.Rng2i32{min:m.Vec2i{x:2,y:0},max:m.Vec2i{x:1,y:1}})',
    'm.rng2f32_overlaps(m.Rng2f32{},m.Rng2f32{min:m.Vec2{x:#cast(f32,m.nan()),y:0.0},max:m.Vec2{x:1.0,y:1.0}})',
    'm.rng2i32_dimension(m.Rng2i32{min:m.Vec2i{x:m.min_value(i32),y:0},max:m.Vec2i{x:m.max_value(i32),y:1}})',
    'm.rng2i32_pad(m.Rng2i32{min:m.Vec2i{x:0,y:0},max:m.Vec2i{x:m.max_value(i32),y:1}},1)',

    'm.rng1i64_dimension(m.Rng1i64{min:2,max:1})',
    'm.rng1i64_dimension(m.Rng1i64{min:m.min_value(i64),max:m.max_value(i64)})',
    'm.rng1u64_pad(m.Rng1u64{min:0,max:2},1)',
    'm.rng1f32_pad(m.Rng1f32{min:0.0,max:2.0},-1.0)',
    'm.rng1f32_dimension(m.Rng1f32{min:#cast(f32,m.nan()),max:1.0})',
]
with tempfile.TemporaryDirectory(prefix='dyn-math-range-') as temporary:
    work = Path(temporary)
    for release in (False, True):
        def build(text):
            (work / 'main.dyn').write_text(text)
            subprocess.run([DYN,'build',str(work),'--no-cache','--quiet','--output',str(work/'test'),
                            *(['--release'] if release else [])],check=True,timeout=120)
        build('\n'.join(source))
        subprocess.run([str(work/'test')],check=True,timeout=20)
        for expression in negative:
            build('use "std/math" m\nfn main() { _='+expression+' }')
            result = subprocess.run([str(work/'test')],capture_output=True,timeout=10)
            assert result.returncode != 0, (expression, result)
        print(f'PASS math ranges {"release" if release else "debug"}: {checks} interval checks, rectangles, wide centers, {len(negative)} rejection cases')
