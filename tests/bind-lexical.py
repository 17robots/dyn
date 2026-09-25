#!/usr/bin/env python3
"""Binding strings agree byte-for-byte with C; const stays on its pointer level."""
import os, runpy, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
api=runpy.run_path(str(ROOT/'tools/dyn-bind.py'))
generate=api['generate']
source=r'''#define MARKER "/*keep*/"
#define URL "https://example.test"
#define BYTES "\101\012\0\xff\a\b\f\v\?\"\\"
#define FAKE "struct Imaginary { int x; };"
#define EMPTY
int actual(void);
void update(const int **value);
void fixed(int *const *value);
void callback(void (*visit)(const int **value));
int unspecified();
void unspecified_callback(void (*visit)());
int unnamed(int);
#define UNICODE "\u0041"
#define TOO_WIDE "\x123"
'''
out=generate(source)
assert 'MARKER: []const u8 = "/*keep*/"' in out,out
assert 'URL: []const u8 = "https://example.test"' in out,out
assert 'value: **const i32' in out,out
assert 'value: *const *i32' in out,out
assert 'visit: *fn(**const i32)' in out,out
assert 'pub struct Imaginary' not in out,out
assert 'pub extern fn actual' in out and 'pub const EMPTY' not in out,out
for name in ('unspecified','unspecified_callback','unnamed'):
    assert f'pub extern fn {name} ' not in out and f'// function {name}:' in out,out
for name in ('UNICODE','TOO_WIDE'):
    assert f'pub const {name}:' not in out and f'// macro {name}:' in out,out
# Splicing precedes comment removal; a continued comment must not expose a macro.
assert 'pub const HIDDEN' not in generate('// comment\\\n#define HIDDEN 1\n')
assert 'pub const SPLIT: u64 = 12' in generate('#define SPLIT 1\\\n2\n')
with tempfile.TemporaryDirectory(prefix='dyn-bind-bytes-') as d:
    root=Path(d)
    # Remove intentionally invalid escape definitions before asking C to compile.
    header='\n'.join(line for line in source.splitlines() if not line.startswith(('#define UNICODE','#define TOO_WIDE')))+'\n'
    (root/'input.h').write_text(header)
    (root/'bindings.dyn').write_text(out)
    c=['#include <stddef.h>','#include "input.h"']
    declarations=[];checks=[]
    for name in ('MARKER','URL','BYTES','FAKE'):
        symbol='check_'+name
        c.append(f'int {symbol}(const unsigned char *data, size_t length) {{ const unsigned char expected[] = {name}; if (length != sizeof(expected)-1) return 0; for (size_t i=0;i<length;++i) if(data[i]!=expected[i]) return 0; return 1; }}')
        declarations.append(f'extern fn {symbol} "{symbol}"(data: *const u8, length: usize) i32')
        checks.append(f'if {symbol}(&{name}[0], #len({name})) != 1 {{ #panic("C literal {name}") }}')
    (root/'provider.c').write_text('\n'.join(c)+'\n')
    (root/'main.dyn').write_text('\n'.join(declarations)+'\nfn main() {\n'+'\n'.join(checks)+'\n}\n')
    subprocess.run(['cc','-std=c11','-fno-stack-protector','-c',str(root/'provider.c'),'-o',str(root/'provider.o')],check=True)
    for release in (False,True):
        subprocess.run([DYN,'build',str(root),'--quiet','--no-cache','--link',str(root/'provider.o'),'--output',str(root/'run')]+(['--release'] if release else []),check=True)
        subprocess.run([str(root/'run')],check=True)
    result=subprocess.run(['python3',str(ROOT/'tools/dyn-bind.py'),str(root/'input.h'),'-o',str(root/'missing/out.dyn')],capture_output=True,text=True)
    assert result.returncode==1 and 'dyn-bind:' in result.stderr and 'Traceback' not in result.stderr,result.stderr
print('PASS C/Dyn literal bytes debug/release, nested pointer constness, lexical boundaries and unsupported prototypes')
