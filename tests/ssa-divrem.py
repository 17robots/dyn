#!/usr/bin/env python3
"""Runtime quotient/remainder reuse: independent integer oracle and panic order."""
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
BASE = Path(os.environ.get('DYN_DIVREM_BASELINE', ROOT / 'build/dyn-before-compiler-next')).resolve()
if sys.platform != 'linux' or os.uname().machine != 'x86_64':
    print('SKIP runtime division pairing requires Linux x86-64 assembly oracle')
    raise SystemExit(0)


def run(command, **kwargs):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True,
                          timeout=120, **kwargs)


functions = ['extern fn observed(value: u64) u64', 'extern fn mutate(value: *u64)']
prototypes = []
for signed in [False, True]:
    wide = 'i64' if signed else 'u64'
    cwide = 'int64_t' if signed else 'uint64_t'
    for bits in [8, 16, 32, 64]:
        ty = ('i' if signed else 'u') + str(bits)
        for reverse in [False, True]:
            name = f'{ty}_{"rq" if reverse else "qr"}'
            operations = ['q := x / y', 'r := x % y']
            if reverse:
                operations.reverse()
            functions.append(f'''pub fn {name}(a: {wide}, b: {wide}, out: *[2]{wide}) {{
  x := #cast({ty}, a)
  y := #cast({ty}, b)
  {operations[0]}
  {operations[1]}
  out.*[0] = #cast({wide}, q)
  out.*[1] = #cast({wide}, r)
}}''')
            prototypes.append(f'extern void {name}({cwide},{cwide},{cwide}*);')
functions.append('''
pub fn live(a,b,c,d,e,f,g,h:u64,out:*[3]u64) {
  q := a / b
  marker := observed(c) ^ d ^ e ^ f ^ g ^ h
  r := a % b
  out.*[0] = q
  out.*[1] = r
  out.*[2] = marker ^ q ^ r
}
pub fn memory(a:u64,b:*u64,out:*[2]u64) {
  q := a / b.*
  mutate(b)
  r := a % b.*
  out.*[0] = q
  out.*[1] = r
}
pub fn sibling(a,b:u64,choice:bool) u64 {
  if choice { return a / b }
  return a % b
}
pub fn dominating(a,b:u64,choice:bool,out:*[2]u64) {
  q := a / b
  r: u64 = 0
  if choice { r = a % b }
  out.*[0] = q
  out.*[1] = r
}
pub fn reverse_dominating(a,b:u64,choice:bool,out:*[2]u64) {
  r := a % b
  q: u64 = 0
  if choice { q = a / b }
  out.*[0] = q
  out.*[1] = r
}
pub fn loop_pair(a,b:u64,out:*[2]u64) {
  quotients: u64 = 0
  remainders: u64 = 0
  for i in 0..31 {
    value := a ^ #cast(u64, i)
    r := value % b
    q := value / b
    quotients ^= q
    remainders ^= r
  }
  out.*[0] = quotients
  out.*[1] = remainders
}
pub fn changed(a,b,c:u64,out:*[2]u64) {
  q := a / b
  r := a % c
  out.*[0] = q
  out.*[1] = r
}
pub fn mixed(a,b:u64,out:*[2]u64) {
  q := a / b
  r := #bitcast(i64,a) % #bitcast(i64,b)
  out.*[0] = q
  out.*[1] = #bitcast(u64,r)
}
''')

# More pairs than the per-function budget: optimized prefixes and untouched
# suffixes must coexist correctly without unbounded insertion work.
stress = ['pub fn stress(a,b:u64) u64 {', '  d := b | 1', '  result: u64 = 0']
for i in range(100):
    stress.extend([f'  x_{i} := a ^ {i}', f'  q_{i} := x_{i} / d',
                   f'  r_{i} := x_{i} % d', f'  result ^= q_{i} ^ r_{i}'])
stress.extend(['  return result', '}'])
functions.append('\n'.join(stress))

rng = random.Random(7827)
cases = {}
for signed in [False, True]:
    for bits in [8, 16, 32, 64]:
        low = -(1 << (bits - 1)) if signed else 0
        high = (1 << (bits - int(signed))) - 1
        edges = {low, low + 1, high, high - 1, 0, 1, 2, 3, 7, 10}
        if signed:
            edges |= {-1, -2, -3, -7, -10}
        pairs = {(a, b) for a in edges for b in edges
                 if low <= a <= high and low <= b <= high and b and not (signed and a == low and b == -1)}
        pairs |= {(rng.randint(low, high), rng.randint(low, high)) for _ in range(1000)}
        pairs = [(a, b) for a, b in sorted(pairs) if b and not (signed and a == low and b == -1)]
        cases[signed, bits] = [(a, b, (abs(a) // abs(b)) * (-1 if (a < 0) != (b < 0) else 1), 0) for a, b in pairs]
        cases[signed, bits] = [(a, b, q, a - q * b) for a, b, q, _ in cases[signed, bits]]


def number(n, signed):
    if signed:
        return 'INT64_MIN' if n == -(1 << 63) else f'INT64_C({n})'
    return f'UINT64_C({n})'


c = '#include <stdint.h>\n#include <stddef.h>\n' + '\n'.join(prototypes) + r'''
extern void live(uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t*);
extern void memory(uint64_t,uint64_t*,uint64_t*);
extern uint64_t sibling(uint64_t,uint64_t,_Bool);
extern void dominating(uint64_t,uint64_t,_Bool,uint64_t*);
extern void reverse_dominating(uint64_t,uint64_t,_Bool,uint64_t*);
extern void loop_pair(uint64_t,uint64_t,uint64_t*);
extern uint64_t stress(uint64_t,uint64_t);
static unsigned calls;
uint64_t observed(uint64_t x){calls++;return x^123;}
void mutate(uint64_t *p){*p=7;calls++;}
'''
for (signed, bits), values in cases.items():
    ty = ('i' if signed else 'u') + str(bits)
    cty = 'int64_t' if signed else 'uint64_t'
    c += f'static const {cty} cases_{ty}[][4]={{\n'
    c += ',\n'.join('{' + ','.join(number(v, signed) for v in row) + '}' for row in values) + '};\n'
c += 'int oracle(void){\n'
for signed, bits in cases:
    ty = ('i' if signed else 'u') + str(bits)
    cty = 'int64_t' if signed else 'uint64_t'
    c += f'''for(size_t i=0;i<sizeof(cases_{ty})/sizeof(cases_{ty}[0]);i++){{
 const {cty} *v=cases_{ty}[i];{cty} out[2];
 {ty}_qr(v[0],v[1],out);if(out[0]!=v[2]||out[1]!=v[3])return {bits};
 {ty}_rq(v[0],v[1],out);if(out[0]!=v[2]||out[1]!=v[3])return {bits+1};
}}\n'''
c += r'''
for(size_t i=0;i<sizeof(cases_u64)/sizeof(cases_u64[0]);i++){
 const uint64_t *v=cases_u64[i];uint64_t out[3],divisor=v[1];
 calls=0;live(v[0],v[1],3,5,7,11,13,17,out);
 if(calls!=1||out[0]!=v[2]||out[1]!=v[3]||out[2]!=((3^123)^5^7^11^13^17^v[2]^v[3]))return 101;
 calls=0;memory(v[0],&divisor,out);
 if(calls!=1||out[0]!=v[2]||out[1]!=v[0]%7||divisor!=7)return 102;
 if(sibling(v[0],v[1],1)!=v[2]||sibling(v[0],v[1],0)!=v[3])return 103;
 for(unsigned b=0;b<2;b++){
  dominating(v[0],v[1],b,out);if(out[0]!=v[2]||out[1]!=(b?v[3]:0))return 104;
  reverse_dominating(v[0],v[1],b,out);if(out[0]!=(b?v[2]:0)||out[1]!=v[3])return 105;
 }
 uint64_t q=0,r=0;for(unsigned j=0;j<31;j++){q^=(v[0]^j)/v[1];r^=(v[0]^j)%v[1];}
 loop_pair(v[0],v[1],out);if(out[0]!=q||out[1]!=r)return 106;
 uint64_t checksum=0;for(unsigned j=0;j<100;j++){checksum^=((v[0]^j)/(v[1]|1))^((v[0]^j)%(v[1]|1));}
 if(stress(v[0],v[1])!=checksum)return 107;
}
return 0;}
'''
source = '\n'.join(functions) + '\nextern fn oracle() i32\nfn main(){ code:=oracle()\nif code!=0 {#panic("division oracle failed")}}\n'
with tempfile.TemporaryDirectory(prefix='dyn-divrem-') as directory:
    work = Path(directory); project = work / 'project'; project.mkdir()
    (project / 'main.dyn').write_text(source)
    (work / 'oracle.c').write_text(c)
    obj = work / 'oracle.o'
    result = run([os.environ.get('CC', 'cc'), '-O2', '-ffreestanding', '-fno-stack-protector', '-c', work / 'oracle.c', '-o', obj])
    assert result.returncode == 0, result.stderr
    for mode, flags in [('debug', ['--debug']), ('release', ['--release']), ('o1', ['--release', '--opt-level', '1']), ('o3', ['--release', '--opt-level', '3']), ('tree', ['--release'])]:
        binary = work / mode
        result = run([DYN, 'build', project, *flags, '--no-cache', '--quiet', '--link', obj, '--output', binary],
                     env={**os.environ, 'DYN_NO_SSA': '1' if mode == 'tree' else '0'})
        assert result.returncode == 0, (mode, result.stderr)
        result = run([binary]); assert result.returncode == 0, (mode, result.stdout, result.stderr)
        if mode in ['release', 'o3']:
            assembly = run(['objdump', '-d', binary]).stdout
            def divisions(name):
                found = re.search(r'<'+re.escape(name)+r'>:\n(.*?)(?=\n[0-9a-f]+ <|\Z)', assembly, re.S)
                assert found, name
                return len(re.findall(r'\b(?:idiv|div)\s', found[1]))
            for name in ['u64_qr', 'u64_rq', 'i64_qr', 'i64_rq', 'dominating']:
                assert divisions(name) == 1, (mode, name, divisions(name))
            assert divisions('stress') == 168, (mode, '32-pair budget', divisions('stress'))
            for name in ['memory', 'changed', 'mixed', 'sibling', 'reverse_dominating']:
                assert divisions(name) == 2, (mode, name, divisions(name))
    # Failures must occur at the same original operation, with identical defer
    # output; checks are never hoisted above a preceding observation or write.
    panic_cases = []
    for signed in [False, True]:
        ty = 'i64' if signed else 'u64'
        for reverse in [False, True]:
            for which in ['zero', 'overflow'] if signed else ['zero']:
                a, b = ('-9223372036854775807 - 1', '-1') if which == 'overflow' else ('37', '0')
                ops = ['q := a / b', 'r := a % b']
                if reverse: ops.reverse()
                panic_cases.append(f'''use "std/io"
fn calculate(a,b:{ty}) {{
 defer io.println("cleanup")
 io.println("before")
 {ops[0]}
 io.println("between {{}}", {'r' if reverse else 'q'})
 {ops[1]}
 io.println("after {{}} {{}}",q,r)
}}
fn main() {{ calculate({a},{b}) }}
''')
    # A wide first operation can succeed before a narrow second operation's
    # overflow check. Its observation must not disappear or move after failure.
    for reverse in [False, True]:
        first_op = '%' if reverse else '/'
        second_op = '/' if reverse else '%'
        panic_cases.append(f'''use "std/io"
fn calculate(a,b:i64) {{
 defer io.println("cleanup")
 io.println("before")
 first := a {first_op} b
 io.println("between {{}}", first)
 second := #cast(i8,a) {second_op} #cast(i8,b)
 io.println("after {{}}", second)
}}
fn main() {{ calculate(-128,-1) }}
''')
    for index, sample in enumerate(panic_cases):
        (project / 'main.dyn').write_text(sample)
        expected = None
        compilers = [BASE, DYN] if BASE.exists() else [DYN]
        for compiler in compilers:
            for flags in [['--debug'], ['--release'], ['--release', '--opt-level', '1'], ['--release', '--opt-level', '3']]:
                binary = work / 'panic'
                result = run([compiler, 'build', project, *flags, '--quiet', '--no-cache', '--output', binary])
                assert result.returncode == 0, result.stderr
                result = run([binary])
                expected_stdout = {6: 'before\nbetween 128\ncleanup\n', 7: 'before\nbetween 0\ncleanup\n'}.get(index, 'before\ncleanup\n')
                assert result.returncode != 0 and result.stdout == expected_stdout, result
                detail = re.search(r'(?:divide|division)[a-zA-Z0-9_.]*', result.stderr)
                expected_kind = 'division.overflow.ok' if index in [3, 5, 6, 7] else 'divide.ok'
                assert detail and detail[0] == expected_kind, result.stderr
                observed = result.stdout, detail[0]
                if expected is None: expected = observed
                assert observed == expected, (observed, expected)
print(f'PASS runtime div/rem: {sum(map(len,cases.values()))*2} oracle pairs per mode, signed/unsigned widths, calls/live values, aliasing, dominance, loops, assembly counts and exact panic/defer order (debug/O1/O2/O3/tree)')
