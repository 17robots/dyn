#!/usr/bin/env python3
"""Whole-server cold/repeated hover latency; same project and requests each run."""
import json
from pathlib import Path
import runpy
import statistics
import tempfile
import time

h = runpy.run_path('tests/lsp-contracts.py')
with tempfile.TemporaryDirectory(prefix='dyn-analysis-bench-') as directory:
    root = Path(directory)
    library = root / 'library'
    library.mkdir()
    (library / 'module.dyn').write_text('pub fn answer() i32 { return 42 }\n' + ''.join(
        f'pub fn helper{i}() i32 {{ return {i} }}\n' for i in range(300)))
    text = 'use "./library"\nfn main() { value := library.answer()\n_ = value\n}\n'
    source = root / 'main.dyn'
    source.write_text(text)
    results = {}
    for requests in (1, 30):
        samples = []
        for _ in range(3):
            messages = [h['opened'](source, text)] + [h['request']('textDocument/hover', {
                'textDocument': {'uri': source.as_uri()},
                'position': {'line': 2, 'character': 5}}, 2 + i) for i in range(requests)]
            start = time.monotonic()
            responses, stderr = h['run_lsp'](messages)
            samples.append(time.monotonic() - start)
            assert not stderr, stderr
            for ident in range(2, 2 + requests):
                assert next(r['result'] for r in responses if r.get('id') == ident)
        results[str(requests)] = {'seconds': samples, 'median_seconds': statistics.median(samples)}
    print(json.dumps(results))
