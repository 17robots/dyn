#!/usr/bin/env python3
"""Measure whole-server warning publication with many unopened sibling declarations."""
import json
from pathlib import Path
import runpy
import statistics
import tempfile
import time

helpers = runpy.run_path('tests/lsp-contracts.py')
with tempfile.TemporaryDirectory(prefix='dyn-lsp-perf-') as directory:
    root = Path(directory)
    text = ''.join(f'const Value{i}: i32 = {i}\n' for i in range(100))
    source = root / 'values.dyn'
    source.write_text(text)
    (root / 'helpers.dyn').write_text(''.join(
        f'pub fn helper{i}() i32 {{ return {i} }}\n' for i in range(1000)))
    timings = []
    for _ in range(3):
        start = time.monotonic()
        responses, stderr = helpers['run_lsp']([helpers['opened'](source, text)])
        timings.append(time.monotonic() - start)
        assert not stderr, stderr
        warnings = helpers['diagnostics'](responses, source)
        assert len(warnings) == 100, warnings
        assert all(warning.get('code') == 'unused-constant' for warning in warnings)
    print(json.dumps({'seconds': timings, 'median_seconds': statistics.median(timings),
                      'warnings': len(warnings)}))
