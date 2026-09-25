#!/usr/bin/env python3
"""Unsupported generic literals must fail in grammar, compiler, and editor."""
from pathlib import Path
import runpy
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
h = runpy.run_path(str(ROOT / 'tests/lsp-contracts.py'))
with tempfile.TemporaryDirectory(prefix='dyn-rejections-') as temporary:
    root = Path(temporary)
    path = root / 'main.dyn'
    (root / 'lib').mkdir()
    (root / 'lib/module.dyn').write_text('pub struct Box { value: i32 }\n')
    prefix = 'use "./lib" lib\nstruct Box { value: i32 }\n'
    literals = ['Box(i32){value: 1}', 'Box(i32, bool){value: 1}', 'lib.Box(i32){value: 1}', 'Box([]const u8){value: 1}']
    count = 0
    for literal in literals:
        for body in [f'const bad := {literal}\nfn main() {{}}',
                     f'fn main() {{ _ = {literal} }}',
                     f'fn main() {{ if true {{ _ = {literal} }} }}',
                     f'fn get() Box {{ return {literal} }}\nfn main() {{}}']:
            text = prefix + body + '\n'
            path.write_text(text)
            parsed = subprocess.run(['tree-sitter', 'parse', '--quiet', str(path)], cwd=ROOT/'tree-sitter-dyn', capture_output=True, text=True)
            assert parsed.returncode != 0, text
            for command in ['check', 'build']:
                result = subprocess.run([h['DYN'], command, str(root), '--quiet', '--no-cache', '--no-link', '--output', str(root/'main.o')], capture_output=True, text=True)
                assert result.returncode != 0 and 'invalid syntax' in result.stderr, (text, result.stderr)
            responses, stderr = h['run_lsp']([h['opened'](path, text)])
            assert not stderr, stderr
            diagnostics = h['diagnostics'](responses, path)
            assert any(d.get('code') == 'syntax' and d['severity'] == 1 for d in diagnostics), text
            assert not any('expected a function body' in d['message'] for d in diagnostics), (text, diagnostics)
            count += 1
    text = 'fn main() { type Local = i32 }\n'
    path.write_text(text)
    result = subprocess.run([h['DYN'], 'check', str(root), '--quiet'], capture_output=True, text=True)
    assert result.returncode != 0 and 'declare the alias at module scope' in result.stderr, result.stderr
    path.write_text('type Local = i32\nfn main() { value: Local = 42 _ = value }\n')
    subprocess.run([h['DYN'], 'check', str(root), '--quiet'], check=True)
    # Syntax ranges use the negotiated wire encoding, not Tree-sitter byte columns.
    for encoding, expected_delta in [('utf-16', 1), ('utf-8', 3)]:
        ranges = []
        for comment in ['x', '😀']:
            text = f'struct Box {{ value: i32 }}\nfn main() {{ /* {comment} */ _ = Box(i32){{value: 1}} }}\n'
            responses, stderr = h['run_lsp']([h['opened'](path, text)], {
                'capabilities': {'general': {'positionEncodings': [encoding]}}})
            assert not stderr, stderr
            ranges.append(h['diagnostics'](responses, path)[0]['range'])
        for end in ['start', 'end']:
            assert ranges[1][end]['character'] - ranges[0][end]['character'] == expected_delta, (encoding, ranges)
print(f'PASS {count} generic literal rejections across parser/check/build/LSP; module-only aliases')
