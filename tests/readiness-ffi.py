#!/usr/bin/env python3
"""Reject Dyn-only foreign storage while allowing C-compatible aggregates."""
import os,runpy,subprocess,tempfile
from pathlib import Path
DYN=str(Path(os.environ.get('DYN','build/dyn-release')).resolve())
prefix='struct Triple { a: []u8 }\n'
cases=[('extern fn sum "sum"(x: Triple) i64','_ = sum(Triple{})'),('extern fn get "get"() Triple','_ = get()'),('extern fn sum "sum"(x: Triple) i64','_ = &sum'),('extern fn apply "apply"(callback: *fn(Triple) i64)','apply(&local)')]
with tempfile.TemporaryDirectory(prefix='dyn-ffi-contract-') as d:
    root=Path(d)
    for declaration,body in cases:
        (root/'main.dyn').write_text(prefix+declaration+'\nfn local(value: Triple) i64 { return 1 }\nfn main() { '+body+' }\n')
        for cmd in ('check','build'):
            r=subprocess.run([DYN,cmd,d,'--quiet','--no-cache','--output',str(root/'out')],capture_output=True,text=True,timeout=30)
            assert r.returncode==1 and 'no supported C ABI' in r.stderr,r.stderr
    (root/'main.dyn').write_text('struct Triple { a: i64, b: i64, c: i64 }\n'+'fn local(value: Triple) Triple { return value }\nfn main() { value := local(Triple{a: 42}) if value.a != 42 { #panic("Dyn ABI") } }\n')
    subprocess.run([DYN,'build',d,'--quiet','--no-cache','--output',str(root/'out')],check=True)
    subprocess.run([str(root/'out')],check=True)
generate=runpy.run_path('tools/dyn-bind.py')['generate']
out=generate('typedef struct Triple { long a; long b; long c; } Triple;\nlong sum(Triple x);\nTriple get(void);\nlong good(const Triple *x);\n')
assert 'pub extern fn sum' in out and 'pub extern fn get' in out and 'pub extern fn good' in out,out
print('PASS Dyn-only foreign storage rejected; aggregate native calls retained')
