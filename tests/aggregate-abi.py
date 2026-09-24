#!/usr/bin/env python3
"""C/Dyn aggregate calls, returns, callbacks and register exhaustion per target.
Native Linux executes against two C compilers; other targets cross-link probes
for native CI. Artifact manifests never label cross-links as executed.
"""
import argparse, json, os, platform, shlex, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--cross', action='store_true')
a = p.parse_args()
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
work = ROOT/'build/aggregate-abi'; work.mkdir(parents=True, exist_ok=True)
# name, C fields, Dyn fields, initializers, member checked/modified, value
cases = [
 ('Byte', 'unsigned char value;', 'value: u8', 'value: 9', 'value', '9'),
 ('Bytes', 'unsigned char data[3];', 'data: [3]u8', 'data: [1, 2, 9]', 'data[2]', '9'),
 ('Pair', 'long long value; double real;', 'value: i64, real: f64', 'value: 9, real: 2.5', 'value', '9'),
 ('Reverse', 'double real; long long value;', 'real: f64, value: i64', 'real: 2.5, value: 9', 'value', '9'),
 ('Two', 'long long other, value;', 'other: i64, value: i64', 'other: 7, value: 9', 'value', '9'),
 ('Triple', 'long long a, b, value;', 'a: i64, b: i64, value: i64', 'a: 1, b: 2, value: 9', 'value', '9'),
 ('Float', 'float value;', 'value: f32', 'value: 2.5', 'value', '2.5'),
 ('Floats', 'float a, value;', 'a: f32, value: f32', 'a: 1.5, value: 2.5', 'value', '2.5'),
 ('ThreeFloats', 'float a, b, value;', 'a: f32, b: f32, value: f32', 'a: 1.5, b: 2.0, value: 2.5', 'value', '2.5'),
 ('FourFloats', 'float a, b, c, value;', 'a: f32, b: f32, c: f32, value: f32', 'a: 1.5, b: 2.0, c: 3.0, value: 2.5', 'value', '2.5'),
 ('Doubles', 'double a, value;', 'a: f64, value: f64', 'a: 1.5, value: 2.5', 'value', '2.5'),
 ('FourDoubles', 'double a, b, c, value;', 'a: f64, b: f64, c: f64, value: f64', 'a: 1.5, b: 2.0, c: 3.0, value: 2.5', 'value', '2.5'),
 ('Nested', 'Floats pair[2];', 'pair: [2]Floats', 'pair: [Floats{a: 1.0, value: 2.0}, Floats{a: 3.0, value: 2.5}]', 'pair[1].value', '2.5'),
 ('Padding', 'unsigned char tag; double value;', 'tag: u8, value: f64', 'tag: 7, value: 2.5', 'value', '2.5'),
 ('Packed', 'unsigned char tag; long long value;', 'tag: u8, value: i64', 'tag: 7, value: 9', 'value', '9'),
 ('Boolean', '_Bool flag; signed char value;', 'flag: bool, value: i8', 'flag: true, value: -9', 'value', '-9'),
]
leaves = {
 'Byte': [('value',9)], 'Bytes': [('data[0]',1),('data[1]',2),('data[2]',9)],
 'Pair': [('value',9),('real',2.5)], 'Reverse': [('real',2.5),('value',9)],
 'Two': [('other',7),('value',9)], 'Triple': [('a',1),('b',2),('value',9)],
 'Float': [('value',2.5)], 'Floats': [('a',1.5),('value',2.5)],
 'ThreeFloats': [('a',1.5),('b',2),('value',2.5)],
 'FourFloats': [('a',1.5),('b',2),('c',3),('value',2.5)],
 'Doubles': [('a',1.5),('value',2.5)],
 'FourDoubles': [('a',1.5),('b',2),('c',3),('value',2.5)],
 'Nested': [('pair[0].a',1),('pair[0].value',2),('pair[1].a',3),('pair[1].value',2.5)],
 'Padding': [('tag',7),('value',2.5)], 'Packed': [('tag',7),('value',9)],
 'Boolean': [('flag',1),('value',-9)],
}
c = ['char c_char_value(void) { return (char)-1; }',
     'int c_char_negative(void) { return (char)-1 < 0; }']
dyn = ['use "std/c"', 'extern fn c_char_value "c_char_value"() c.char',
       'extern fn c_char_negative "c_char_negative"() i32']
body = ['plain_char := c_char_value()',
        'if #sizeof(c.char) != 1 || (plain_char < 0) != (c_char_negative() != 0) { #panic("C char signedness") }']
for name, cf, df, init, field, expected in cases:
    packed = name == 'Packed'
    increment = '1.0' if '.' in expected else '1'
    updated = str(float(expected)+1) if '.' in expected else str(int(expected)+1)
    c.append(f'typedef struct {"__attribute__((packed))" if packed else ""} {{ {cf} }} {name};')
    dyn.append(f'{"packed " if packed else ""}struct {name} {{ {df} }}')
    c += [f'{name} c_{name}({name} x) {{ x.{field} += 1; return x; }}',
          f'{name} cb_{name}({name} (*f)({name}), {name} x) {{ return f(x); }}']
    dyn += [f'extern fn c_{name} "c_{name}"(x: {name}) {name}',
            f'extern fn cb_{name} "cb_{name}"(f: *fn({name}) {name}, x: {name}) {name}',
            f'fn local_{name}(x: {name}) {name} {{ value := x value.{field} += {increment} return value }}']
    checksum = '+'.join(f'{2*i+1}*(double)x.{path}' for i,(path,_) in enumerate(leaves[name]))
    total = float(sum((2*i+1)*(value + (path == field)) for i,(path,value) in enumerate(leaves[name])))
    c.append(f'double sum_{name}({name} x) {{ return {checksum}; }}')
    dyn.append(f'extern fn sum_{name} "sum_{name}"(x: {name}) f64')
    body += [f'x_{name} := {name}{{{init}}}',
             f'r_{name} := c_{name}(x_{name})',
             f'if sum_{name}(r_{name}) != {total} {{ #panic("all fields {name}") }}',
             f'if r_{name}.{field} != {updated} || x_{name}.{field} != {expected} {{ #panic("direct {name}") }}',
             f'f_{name} := &c_{name}', f'r_{name} = f_{name}(x_{name})',
             f'if r_{name}.{field} != {updated} {{ #panic("indirect {name}") }}',
             f'r_{name} = cb_{name}(&local_{name}, x_{name})',
             f'if sum_{name}(r_{name}) != {total} {{ #panic("callback fields {name}") }}',
             f'if r_{name}.{field} != {updated} {{ #panic("callback {name}") }}']
# A two-register struct cannot partially consume the final SysV argument register.
c += ['long long pressure(long long a,long long b,long long c,long long d,long long e,Two x,long long tail) { return a+b+c+d+e+x.other+x.value+tail; }',
      'double fp_pressure(double a,double b,double c,double d,double e,double f,double g,Doubles x,double tail) { return a+b+c+d+e+f+g+x.a+x.value+tail; }',
      'double independent(long long a,long long b,long long c,long long d,long long e,long long f,long long g,Doubles x) { return a+b+c+d+e+f+g+x.a+x.value; }']
dyn += ['extern fn pressure "pressure"(a:i64,b:i64,c:i64,d:i64,e:i64,x:Two,tail:i64) i64',
        'extern fn fp_pressure "fp_pressure"(a:f64,b:f64,c:f64,d:f64,e:f64,f:f64,g:f64,x:Doubles,tail:f64) f64',
        'extern fn independent "independent"(a:i64,b:i64,c:i64,d:i64,e:i64,f:i64,g:i64,x:Doubles) f64']
body += ['if pressure(1,2,3,4,5,Two{other:7,value:9},11) != 42 { #panic("GP pressure") }',
         'if fp_pressure(1.0,2.0,3.0,4.0,5.0,6.0,7.0,Doubles{a:1.5,value:2.5},10.0) != 42.0 { #panic("FP pressure") }',
         'if independent(1,2,3,4,5,6,7,Doubles{a:1.5,value:2.5}) != 32.0 { #panic("independent classes") }']
source = work/'source'; source.mkdir(exist_ok=True)
(source/'char_linux_arm.dyn').write_text('#target(kernel: linux, arch: aarch64)\nfn check_unsigned_char() { value: c.char = 255 _ = value }\n')
(source/'main.dyn').write_text('\n'.join(dyn)+'\nfn main() {\n'+'\n'.join(body)+'\n}\n')
(work/'provider.c').write_text('\n'.join(c)+'\n')
targets = [('linux','x86_64-linux',shlex.split(os.environ.get('CC','cc')),True),
           ('linux-clang','x86_64-linux',['clang','--sysroot=/'],True)]
if a.cross:
    targets += [(name,target,['zig','cc','-target',triple],False) for name,target,triple in (
        ('windows','x86_64-windows','x86_64-windows-gnu'),('macos','aarch64-macos','aarch64-macos-none'),('aarch64','aarch64-linux','aarch64-linux-musl'))]
rows=[]
for name,target,cc,native in targets:
    for release in (False,True):
        mode='release' if release else 'debug'
        obj=work/f'{name}-{mode}.o'
        subprocess.run([*cc,'-std=c11','-O2' if release else '-O0','-ffreestanding','-fno-sanitize=all','-fno-stack-protector','-c',str(work/'provider.c'),'-o',str(obj)],check=True)
        output=work/(f'{name}-{mode}'+('.exe' if name=='windows' else ''))
        subprocess.run([DYN,'build',str(source),'--target',target,'--no-cache','--quiet','--link',str(obj),'--output',str(output)]+(['--release'] if release else []),check=True,timeout=120)
        if native: subprocess.run([str(output)],check=True,timeout=30)
        rows.append(dict(target=target,provider=cc,release=release,artifact=str(output.relative_to(ROOT)),status='executed' if native else 'cross-linked-only'))
        print('PASS',name,mode,'executed' if native else 'cross-linked',flush=True)
(work/'results.json').write_text(json.dumps(dict(struct_shapes=len(cases),host=platform.platform(),results=rows),indent=2)+'\n')
