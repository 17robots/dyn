#!/usr/bin/env python3
"""Reproducible whole-server completion cost; includes SDK and workspace discovery."""
import json
from pathlib import Path
import runpy
import statistics
import tempfile
import time
h=runpy.run_path('tests/lsp-contracts.py')
with tempfile.TemporaryDirectory(prefix='dyn-autoimport-bench-') as directory:
    root=Path(directory)
    for index in range(200):
        p=root/f'library{index}';p.mkdir()
        (p/'module.dyn').write_text(f'pub fn Zebra{index}() i32 {{ return {index} }}\n')
    source=root/'main.dyn';text='fn main() { Zeb }';source.write_text(text)
    results={}
    for count in (1,30):
        samples=[]
        for _ in range(3):
            messages=[h['opened'](source,text)]+[h['request']('textDocument/completion',{'textDocument':{'uri':source.as_uri()},'position':{'line':0,'character':15}},i+2) for i in range(count)]
            start=time.monotonic();responses,stderr=h['run_lsp'](messages);samples.append(time.monotonic()-start)
            assert not stderr,stderr
            assert all('result' in r for r in responses if isinstance(r.get('id'),int) and 2<=r['id']<count+2)
        results[str(count)]={'seconds':samples,'median_seconds':statistics.median(samples)}
    results['incremental_seconds_per_request']=(results['30']['median_seconds']-results['1']['median_seconds'])/29
    print(json.dumps(results,indent=2))
