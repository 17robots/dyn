#!/usr/bin/env python3
"""Project-aware diagnostics for real first-party projects and SDK libraries."""
from pathlib import Path
import runpy

helpers = runpy.run_path(str(Path(__file__).with_name('lsp-contracts.py')))
checked = 0
for base in ('compiler/std', 'compiler/vendor', 'projects'):
    for directory in sorted({p.parent for p in Path(base).rglob('*.dyn')}):
        # Native non-Linux modules retain their separate check-modules coverage.
        # Wasm projects are exercised with their explicit editor target.
        if '/os/macos' in str(directory) or '/os/windows' in str(directory):
            continue
        target = 'wasm32-wasi' if '/os/wasi' in str(directory) or directory.name == 'wasi-hello' else 'wasm32-browser' if directory.name in ('browser-canvas', 'browser-video') else None
        files = sorted(directory.glob('*.dyn'))
        assert files, directory
        responses, stderr = helpers['run_lsp']([
            helpers['opened'](path.resolve(), path.read_text()) for path in files], target=target)
        assert not stderr, (str(directory), stderr)
        for path in files:
            diagnostics = helpers['diagnostics'](responses, path.resolve())
            errors = [item for item in diagnostics if item.get('severity') == 1]
            assert not errors, (str(path), errors)
            checked += 1
assert checked > 0, 'project coverage must not be empty'
print(f'LSP checked {checked} project/SDK files')
