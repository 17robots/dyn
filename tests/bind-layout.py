#!/usr/bin/env python3
"""Binding reports and layout verification must expose omissions and mismatches."""
import json, os, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-bind-test-') as directory:
    root=Path(directory); header=root/'sample.h'; report=root/'report.json'; output=root/'bindings.dyn'
    header.write_text('struct Record { unsigned char tag; long value; };\nstruct Record transform(struct Record value);\nunion Unsupported { int a; double b; };\n#define SHIFT (1 << 2)\n')
    command=['python3',str(ROOT/'tools/dyn-bind.py'),str(header),'--report',str(report),'--verify-layout','x86_64-linux','--run-layout','--dyn',DYN,'-o',str(output)]
    subprocess.run(command,check=True)
    result=json.loads(report.read_text())
    assert result['layout_verification']['status']=='executed' and result['layout_verification']['checks']==4,result
    assert {(x['kind'],x['name']) for x in result['unsupported']}=={('union','Unsupported'),('macro','SHIFT')},result
    assert all(x['line'] for x in result['unsupported']),result
    assert 'pub extern fn transform' in output.read_text()
    # The text frontend cannot infer pragma packing. C is the independent oracle.
    header.write_text('#pragma pack(push,1)\nstruct Record { unsigned char tag; long value; };\n#pragma pack(pop)\n')
    r=subprocess.run(command,capture_output=True,text=True)
    assert r.returncode==1 and 'layout verification failed' in r.stderr,r.stderr
    assert json.loads(report.read_text())['layout_verification']['status']=='failed'
print('PASS structured binding omissions, C layout oracle, and packing mismatch rejection')
