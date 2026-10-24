#!/usr/bin/env python3
"""Constant global byte fills: exact extents, memory barriers and live registers."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())


def success_source():
    lines = ['use "std/io"']
    checks = []
    names = []
    for n in (64, 65, 131, 8195):
        for byte in (0, 1, 128, 255):
            name = f'fill_{n}_{byte}'
            array = f'data_{n}_{byte}'
            names.append(name)
            lines += [f'{array}: [{n+3}]u8', f'''pub fn {name}(a,b,c,d,e,f,g,h:u64) u64 {{
  held:=#wrap(a+b*3+c*5+d*7+e*11+f*13+g*17+h*19)
  before:={array}[0]
  for i in 0..{n} {{ {array}[i]={byte} }}
  after:={array}[0]
  return #wrap(held+a+b+c+d+e+f+g+h+#cast(u64,before)*257+#cast(u64,after))
}}''']
            held = sum(a*b for a,b in zip(range(11,19), (1,3,5,7,11,13,17,19)))
            checks += [f'''{array}[0]=17
{array}[{n}]=91 {array}[{n+1}]=92 {array}[{n+2}]=93
if {name}(11,12,13,14,15,16,17,18)!={held+sum(range(11,19))+17*257+byte} {{ #panic("live/barrier {name}") }}
for i in 0..{n} {{ if {array}[i]!={byte} {{ #panic("fill {name}") }} }}
if {array}[{n}]!=91 || {array}[{n+1}]!=92 || {array}[{n+2}]!=93 {{ #panic("extent {name}") }}''']
    # A call between fills must observe the first fill, and a subsequent load
    # must observe the second. A surrounding loop must repeat the fill.
    lines += ['''whole: [129]u8
pub fn full_length() { for i in 0..#len(whole) { whole[i]=128 } }
data: [67]u8
seen:u64
pub fn observe() { seen+=#cast(u64,data[0]) data[1]=99 }
pub fn repeated(rounds:usize) {
  for round in 0..rounds {
    for i in 0..64 { data[i]=128 }
    observe()
    for i in 0..65 { data[i]=255 }
    if data[0]!=255 || data[1]!=255 { #panic("call barrier") }
  }
}''']
    checks += ['full_length() for b in whole { if b!=128 { #panic("array length") } }',
               'data[65]=77 data[66]=78 repeated(3) if seen!=384 || data[65]!=77 || data[66]!=78 { #panic("repeated/canary") }']
    return '\n'.join(lines+['fn main() {', *checks, '_=io.write_all(io.stdout(),"OK\\n")', '}']), names


REJECT = '''use "std/io"
small: [64]u8
wide: [64]u16
calls: u64
pub fn effect() u8 { calls+=1 return 1 }
pub fn dynamic(n:usize) { for i in 0..n { small[i]=1 } }
pub fn side_effect() { for i in 0..64 { small[i]=effect() } }
pub fn offset() { for i in 1..64 { small[i]=128 } }
pub fn local() u8 { a:[64]u8 for i in 0..64 { a[i]=255 } return a[0] }
pub fn indirect(p:*[64]u8) { for i in 0..64 { p.*[i]=128 } }
pub fn pointer_length(p:*[64]u8) { for i in 0..#len(p.*) { small[i]=1 } }
pub fn sliced(p:[]u8) { for i in 0..#len(p) { small[i]=1 } }
pub fn observed(p:[]u8) []u8 { calls+=1 return p }
pub fn effect_length() { for i in 0..#len(observed(small[..])) { small[i]=1 } }
pub fn short() { for i in 0..63 { small[i]=1 } }
pub fn other_type() { for i in 0..64 { wide[i]=255 } }
pub fn extra() { for i in 0..64 { small[i]=1 calls+=1 } }
pub fn too_far() { for i in 0..65 { small[i]=1 } }
'''
CASES = [
    ('success', *success_source(), '', 'OK\n'),
    ('rejected', REJECT+'''fn main() {
small[0]=77 offset() if small[0]!=77 { #panic("offset") }
side_effect() if calls!=64 { #panic("effects") }
extra() if calls!=128 { #panic("extra") }
dynamic(64) other_type() short()
if local()!=255 || wide[63]!=255 { #panic("fallback") }
indirect(&small) if small[0]!=128 || small[63]!=128 { #panic("pointer fallback") }
pointer_length(&small) sliced(small[..]) effect_length()
if calls!=129 || small[63]!=1 { #panic("length expression fallback") }
_=io.write_all(io.stdout(),"OK\\n")
}''', [], '', 'OK\n'),
    ('overbound', REJECT+'fn main() { too_far() }', [], 'index.ok', ''),
    ('dynamic-overbound', REJECT+'fn main() { dynamic(65) }', [], 'index.ok', ''),
]


def main():
    targets = [('x86_64-linux', [])]
    for target, executable in [('aarch64-linux', 'qemu-aarch64'), ('riscv64-linux', 'qemu-riscv64'),
                               ('x86_64-windows', 'wine')]:
        if shutil.which(executable):
            targets.append((target, [executable]))
    with tempfile.TemporaryDirectory(prefix='dyn-byte-fill-') as temporary:
        work = Path(temporary)
        for target, runner in targets:
            for mode in ('ssa', 'tree'):
                env = dict(os.environ, DYN_SDK=str(ROOT), WINEDEBUG='-all')
                env.pop('DYN_NO_SSA', None)
                if mode == 'tree':
                    env['DYN_NO_SSA'] = '1'
                for name, source, names, panic, stdout in CASES:
                    (work/'main.dyn').write_text(source)
                    binary = work/('test.exe' if target.endswith('windows') else 'test')
                    build = subprocess.run([DYN, 'build', str(work), '--release', '--opt-level', '3',
                        '--opt-remarks', '--no-cache', '--quiet', '--target', target, '--output', str(binary)],
                        env=env, capture_output=True, text=True, timeout=120)
                    assert build.returncode == 0, (target, mode, name, build.stderr)
                    bulk = 'bulk byte fill' in build.stderr
                    expected = mode == 'ssa' and target.startswith('x86_64') and name == 'success'
                    assert bulk == expected, (target, mode, name, build.stderr)
                    if expected:
                        assert 'bulk byte fill 129 elements with 128' in build.stderr, build.stderr
                        for function in names:
                            assert re.search(r'remark: '+function+r': bulk byte fill ', build.stderr), build.stderr
                            assert re.search(r'remark: '+function+r': SSA code generation,', build.stderr), build.stderr
                        inspect = binary
                        if target.endswith('windows'):
                            # Linked PE images omit the COFF symbol table.
                            inspect = work/'inspect.o'
                            subprocess.run([DYN, 'build', str(work), '--release', '--opt-level', '3',
                                '--no-cache', '--quiet', '--target', target, '--emit-object', '--no-link',
                                '--output', str(work/'inspect')], env=env, check=True,
                                capture_output=True, text=True, timeout=120)
                        dis = subprocess.run(['objdump', '-d', '-Mintel', str(inspect)], check=True,
                                             capture_output=True, text=True, timeout=15).stdout
                        functions = re.split(r'\n(?=[0-9a-f]+ <)', dis)
                        for function in names:
                            bodies = [f for f in functions if re.match(r'[0-9a-f]+ <'+function+r'>:', f)]
                            assert len(bodies) == 1 and 'rep stos' in bodies[0], (function, bodies)
                            if target.endswith('windows'):
                                assert re.search(r'\bpush\s+rdi\b', bodies[0]), bodies[0]
                                assert re.search(r'\bpop\s+rdi\b', bodies[0]), bodies[0]
                    result = subprocess.run([*runner, str(binary)], env=env, capture_output=True,
                                            text=True, timeout=45)
                    assert result.stdout.replace('\r\n','\n') == stdout, (target, mode, name, result)
                    if panic:
                        assert result.returncode != 0 and panic in result.stderr.lower(), (target, mode, name, result)
                    else:
                        assert result.returncode == 0, (target, mode, name, result)
                print(f'PASS byte fill {target} {mode}: extents, bytes, live values, barriers and fallbacks', flush=True)

if __name__ == '__main__':
    main()
