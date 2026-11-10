#!/usr/bin/env python3
"""The language server treats a lone file that declares main, in a directory
without main.dyn or dyn.project, as a program of its own: its neighbours are
other programs, std imports resolve, and each file gets only its own errors."""
import importlib.util
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('DYN', str(ROOT / 'build/dyn-release'))
spec = importlib.util.spec_from_file_location('navigation', ROOT / 'tests/lsp-navigation.py')
navigation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(navigation)

HELLO = 'use "std/io"\n\nfn greet() i32 {\n  return 7\n}\n\nfn main() {\n  io.println("hello {}", greet())\n}\n'
OTHER = 'fn main() {\n  x: u8 = true\n  _ = x\n}\n'
with tempfile.TemporaryDirectory(prefix='dyn-lsp-single-') as directory:
    root = Path(directory).resolve()
    (root / 'hello.dyn').write_text(HELLO)
    (root / 'other.dyn').write_text(OTHER)
    hello = {'uri': (root / 'hello.dyn').as_uri()}
    other = {'uri': (root / 'other.dyn').as_uri()}
    position = {'line': 7, 'character': 26}
    responses = navigation.run([
        navigation.message('textDocument/didOpen', {'textDocument': dict(hello, languageId='dyn', version=1, text=HELLO)}),
        navigation.message('textDocument/didOpen', {'textDocument': dict(other, languageId='dyn', version=1, text=OTHER)}),
        navigation.message('textDocument/hover', {'textDocument': hello, 'position': position}, 2),
        navigation.message('textDocument/definition', {'textDocument': hello, 'position': position}, 3),
    ], root)
    latest = {}
    for response in responses:
        if response.get('method') == 'textDocument/publishDiagnostics':
            latest[response['params']['uri']] = [d['message'] for d in response['params']['diagnostics']]
    assert latest.get(hello['uri']) == [], latest
    assert latest.get(other['uri']) and all('main.dyn' not in m for m in latest[other['uri']]), latest
    results = {r.get('id'): r.get('result') for r in responses if 'id' in r}
    assert results[2]['contents']['value'] == 'fn greet() i32', results[2]
    assert results[3]['uri'] == hello['uri'] and results[3]['range']['start']['line'] == 2, results[3]
print('PASS language server: lone program files beside each other, std imports, hover and definition')
