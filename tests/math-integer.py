#!/usr/bin/env python3
"""Independent bigint oracle, opaque binary runtime operands, debug/release."""
from collections import Counter
import math
import os
from pathlib import Path
import random
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
TYPES = [(f'{s}{w}', w, s == 'i') for w in (8, 16, 32, 64) for s in ('i', 'u')]
TYPES += [('isize', struct.calcsize('P') * 8, True), ('usize', struct.calcsize('P') * 8, False)]
HEADER = '''use "std/math"
use "std/fs"
use "std/mem"
fn require(ok: bool, label: []const u8) { if !ok { #panic(label) } }
fn read(data: []const u8, cursor: *usize) u64 {
  result: u64 = 0
  i: usize = 0
  for i < 8 {
    result |= #cast(u64, data[cursor.*]) << #cast(u64, i * 8)
    cursor.* += 1
    i += 1
  }
  return result
}
'''

def generate(t, w, signed, path):
    lo, hi = (-(1 << (w-1)), (1 << (w-1))-1) if signed else (0, (1 << w)-1)
    mask = (1 << w)-1
    rng = random.Random(7301 + w + signed)
    edges = {lo, lo+1, hi, hi-1, 0, 1, 2, 3, hi//2, *([-1, -2] if signed else [])}
    for bit in range(w):
        for delta in (-1, 0, 1):
            edges.update(v for v in ((1 << bit)+delta, -(1 << bit)+delta) if lo <= v <= hi)
    edges = sorted(edges)
    pairs = ((a, b) for a in range(lo, hi+1) for b in range(lo, hi+1)) if w == 8 else iter([(a,b) for a in edges for b in edges] + [(rng.randint(lo, hi), rng.randint(lo, hi)) for _ in range(1000)])
    checks = []
    def add(expr, value):
        checks.append((expr, value))
    count = 0
    coverage = Counter()
    with path.open('wb') as out:
        for a,b in pairs:
            checks = []
            add('math.is_signed(T)', signed)
            add('math.min_value(T)', lo)
            add('math.max_value(T)', hi)
            for op, symbol, result in [('add','+',a+b), ('sub','-',a-b), ('mul','*',a*b)]:
                overflow = not lo <= result <= hi
                add(f'math.{op}_overflows(a, b)', overflow)
                add(f'math.saturating_{op}(a, b)', max(lo, min(hi, result)))
                # Ordinary checked operations are executed only when the bigint oracle says safe.
                add(f'a {symbol} b' if not overflow else 'a', result if not overflow else a)
            add('math.min(a, b)', min(a,b)); add('math.max(a, b)', max(a,b))
            add('math.clamp(a, math.min(a, b), math.max(a, b))', a)
            bits = a & mask
            add('math.count_ones(a)', bits.bit_count())
            add('math.leading_zeros(a)', w-bits.bit_length())
            add('math.trailing_zeros(a)', (bits & -bits).bit_length()-1 if bits else w)
            shift = (b & 0xffffffff) % w
            add('math.rotate_left(a, #cast(u32, b))', ((bits << shift) | (bits >> ((w-shift)%w))) & mask)
            add('math.rotate_right(a, #cast(u32, b))', ((bits >> shift) | (bits << ((w-shift)%w))) & mask)
            add('math.is_pow2(a)', a > 0 and a & (a-1) == 0)
            add('math.sign(a)', (a > 0)-(a < 0))
            add('math.abs(a)' if a != lo or not signed else 'a', abs(a) if a != lo or not signed else a)
            add('math.isqrt(a)' if a >= 0 else 'a', math.isqrt(a) if a >= 0 else a)
            power = 1 << max(0, (a-1).bit_length()) if a > 1 else 1
            add('math.next_pow2(a)' if power <= hi else 'a', power if power <= hi else a)
            alignment = 1 << ((b & mask) % (w-1 if signed else w))
            down = a // alignment * alignment
            up = -(-a // alignment) * alignment
            add(f'math.align_down(a, #cast(T, {alignment}))', down)
            add(f'math.align_up(a, #cast(T, {alignment}))' if up <= hi else 'a', up if up <= hi else a)
            add('math.div_ceil(a, b)' if a >= 0 and b > 0 else 'a', (a+b-1)//b if a >= 0 and b > 0 else a)
            g = math.gcd(a,b); l = math.lcm(a,b)
            add('math.gcd(a, b)' if g <= hi else 'a', g if g <= hi else a)
            add('math.lcm(a, b)' if l <= hi else 'a', l if l <= hi else a)
            # Expression selection varies by record: store oracle validity flags instead.
            fields = [a & ((1<<64)-1), b & ((1<<64)-1)]
            for expr, expected in checks:
                fields.append(int(expected) & ((1<<64)-1))
            # Each row carries operation-valid flags and alignment; source uses runtime branches.
            flags = [lo<=a+b<=hi, lo<=a-b<=hi, lo<=a*b<=hi, a != lo or not signed, a>=0, power<=hi, up<=hi, a>=0 and b>0, g<=hi, l<=hi]
            coverage.update(name for name, valid in zip(('checked_add','checked_sub','checked_mul','abs','isqrt','next_pow2','align_up','div_ceil','gcd','lcm'), flags) if valid)
            fields.extend([int(x) for x in flags]); fields.append(alignment)
            out.write(struct.pack('<'+'Q'*len(fields), *fields)); count += 1
    # Stable runtime expressions; all expectations above come exclusively from Python integers.
    exprs = [x[0] for x in checks]
    replacements = {5:('a + b',0),8:('a - b',1),11:('a * b',2),22:('math.abs(a)',3),23:('math.isqrt(a)',4),24:('math.next_pow2(a)',5),26:('math.align_up(a, alignment)',6),27:('math.div_ceil(a, b)',7),28:('math.gcd(a, b)',8),29:('math.lcm(a, b)',9)}
    exprs[25] = 'math.align_down(a, alignment)'
    body = f'fn test_{t}(data: []const u8) {{\n cursor: usize = 0\n for cursor < #len(data) {{\n a := #cast({t}, read(data, &cursor))\n b := #cast({t}, read(data, &cursor))\n'
    for i in range(len(exprs)): body += f' e{i} := read(data, &cursor)\n'
    for i in range(10): body += f' f{i} := read(data, &cursor) != 0\n'
    body += f' alignment := #cast({t}, read(data, &cursor))\n'
    for i,expr in enumerate(exprs):
        cond = None
        if i in replacements:
            expr, flag = replacements[i]; cond = f'f{flag}'
        expr = expr.replace('T',t)
        comparison = f'#cast(u64, {expr}) == e{i}'
        if i in (0,3,6,9,20): comparison = f'({expr}) == (e{i} != 0)'
        # Signed narrow values have full u64 sign extension, rotations compare masked bits.
        if i in (18,19): comparison = f'(#cast(u64, {expr}) & {mask}) == e{i}'
        assertion = f'require({comparison}, "{t} {i} {expr}")'
        body += (f' if {cond} {{ {assertion} }} else {{ require(#cast(u64, a) == e{i}, "skipped") }}' if cond else assertion)+'\n'
    return body+' }\n}\n', count, coverage


def limits(w, signed):
    return (-(1 << (w-1)), (1 << (w-1))-1) if signed else (0, (1 << w)-1)


def extra_cases(work):
    """Cross-type conversions and runtime panic cases share an opaque input file."""
    narrow_source = ''
    narrow_calls = ''
    panic_bodies = []
    successes = 0
    for target, tw, ts in TYPES:
        tl, th = limits(tw, ts)
        for origin, ow, osigned in TYPES:
            ol, oh = limits(ow, osigned)
            values = sorted({ol, ol+1, oh-1, oh, 0, 1,
                             *([tl-1, tl, tl+1, th-1, th, th+1]), -1})
            values = list(range(ol, oh+1)) if ow == 8 else [v for v in values if ol <= v <= oh]
            valid = [v for v in values if tl <= v <= th]
            fixture = work/f'narrow-{target}-{origin}.bin'
            fixture.write_bytes(b''.join(struct.pack('<Q', v & ((1<<64)-1)) for v in valid))
            name = f'narrow_{target}_{origin}'
            narrow_source += f"fn {name}(data: []const u8) {{ cursor: usize = 0\n for cursor < #len(data) {{ raw := read(data, &cursor)\n value := #cast({origin}, raw)\n require(#cast(u64, math.narrow({target}, value)) == raw, \"{name}\") }} }}\n"
            narrow_calls += f'if true {{ input := fs.read_all(arena, "{fixture}", 134217728)\n require(input.ok, "narrow input")\n {name}(input.value)\n mem.arena_reset(arena) }}\n'
            successes += len(valid)
            for value in values:
                if not tl <= value <= th:
                    panic_bodies.append((f'_ = math.narrow({target}, #cast({origin}, raw))', value, 0, 'narrow: value does not fit'))
        for expr, a, b, message in [
            ('math.align_up(a, b)', 1, 0, 'alignment must be a power of two'),
            ('math.align_down(a, b)', 1, 3, 'alignment must be a power of two'),
            ('math.align_up(a, b)', th, 2, 'overflow'),
            ('math.next_pow2(a)', th, 0, 'next_pow2 overflows'),
            ('math.div_ceil(a, b)', 1, 0, 'div_ceil requires'),
            ('math.lcm(a, b)', th, th-1, 'lcm overflows'),
            ('a + b', th, 1, 'overflow'),
            ('a - b', tl, 1, 'overflow'),
            ('a * b', th, 2, 'overflow'),
            ('math.clamp(a, b, a)', 0, 1, 'clamp minimum exceeds maximum'),
        ]:
            panic_bodies.append((f'a := #cast({target}, raw)\n b := #cast({target}, other)\n _ = {expr}',a,b,message))
        if ts:
            for expr,a,b,message in [
                ('math.abs(a)',tl,0,'overflow'),
                ('math.gcd(a, b)',tl,0,'gcd overflows'),
                ('math.lcm(a, b)',tl,1,'lcm overflows'),
                ('math.isqrt(a)',-1,0,'isqrt of a negative'),
                ('math.div_ceil(a, b)',-1,1,'div_ceil requires'),
                ('math.div_ceil(a, b)',1,-1,'div_ceil requires'),
                ('math.align_down(a, b)',1,-2,'alignment must be a power of two'),
            ]:
                panic_bodies.append((f'a := #cast({target}, raw)\n b := #cast({target}, other)\n _ = {expr}',a,b,message))
    fixture = work/'panic.bin'
    panic_source = HEADER + 'fn main() { arena := mem.arena_create(4096)\n'
    panic_source += f'input := fs.read_all(arena, "{fixture}", 4096)\n require(input.ok, "panic input")\n cursor: usize = 0\n selector := read(input.value, &cursor)\n raw := read(input.value, &cursor)\n other := read(input.value, &cursor)\n'
    for index,(body,_,_,_) in enumerate(panic_bodies):
        panic_source += f'if selector == {index} {{ {body} }}\n'
    panic_source += '}\n'
    narrow_source += 'fn narrow_all() { arena := mem.arena_create(134217728)\n'+narrow_calls+'mem.arena_release(arena) }\n'
    return narrow_source, panic_source, fixture, panic_bodies, successes


def run():
    with tempfile.TemporaryDirectory(prefix='dyn-math-integer-') as temp:
        work = Path(temp); project = work/'project'; project.mkdir()
        extra, panic_source, panic_fixture, panics, narrow_count = extra_cases(work)
        source = HEADER + extra; total = 0; coverage = Counter(); calls = 'narrow_all()\n'
        for t,w,signed in TYPES:
            path = work/f'{t}.bin'
            body,count,eligible = generate(t,w,signed,path); source += body; total += count; coverage.update(eligible)
            calls += f'if true {{ arena := mem.arena_create(134217728)\n input := fs.read_all(arena, "{path}", 134217728)\n require(input.ok, "read fixture")\n test_{t}(input.value)\n mem.arena_release(arena) }}\n'
        source += 'fn main() {\n'+calls+'}\n'
        (project/'main.dyn').write_text(source)
        for mode in ('--debug','--release'):
            exe = work/mode[2:]
            subprocess.run([DYN,'build',str(project),mode,'--no-cache','--quiet','--output',str(exe)],cwd=ROOT,check=True,timeout=180)
            subprocess.run([str(exe)],check=True,timeout=120)
            (project/'main.dyn').write_text(panic_source)
            panic_exe = work/('panic'+mode[2:])
            subprocess.run([DYN,'build',str(project),mode,'--no-cache','--quiet','--output',str(panic_exe)],cwd=ROOT,check=True,timeout=180)
            for index,(_,a,b,message) in enumerate(panics):
                panic_fixture.write_bytes(struct.pack('<QQQ',index,a & ((1<<64)-1),b & ((1<<64)-1)))
                result = subprocess.run([str(panic_exe)],capture_output=True,text=True,timeout=10)
                assert result.returncode != 0 and message in result.stderr, (mode,index,panics[index],result.returncode,result.stderr)
            (project/'main.dyn').write_text(source)
        print(f'PASS {narrow_count} narrow successes across 100 type pairs; {len(panics)} panic cases per mode')
        print(f'PASS {total} bigint pair cases, {total*30} oracle slots, all 10 integer types, debug/release')
        print('Eligible runtime operations per mode:', dict(sorted(coverage.items())))

if __name__ == '__main__': run()
