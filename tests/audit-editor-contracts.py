#!/usr/bin/env python3
"""Audit editor capacity and module scope without modifying production sources."""
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/repository-audit'
spec = importlib.util.spec_from_file_location('contracts', ROOT / 'tests/lsp-contracts.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
root = OUT / 'lsp-limit'
root.mkdir(parents=True, exist_ok=True)
messages = []
for i in range(33):
    folder = root / str(i)
    folder.mkdir(exist_ok=True)
    p = folder / 'main.dyn'
    p.write_text('fn main() {}\n')
    messages.append(m.opened(p, 'fn main() { value: i32 = true\n_ = value }\n'))
messages.append(m.request('textDocument/documentSymbol', {'textDocument': {'uri': p.as_uri()}}, 2))
responses, stderr = m.run_lsp(messages)
publication = {r['params']['uri'] for r in responses if r.get('method') == 'textDocument/publishDiagnostics'}
result = {'published_document_count': len(publication), 'last_document_diagnostics': p.as_uri() in publication,
          'last_document_symbols': next(r for r in responses if r.get('id') == 2), 'stderr': stderr}
(root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
assert result['published_document_count'] == 33 and result['last_document_diagnostics']
assert result['last_document_symbols']['result']
print('PASS 33 open documents')
root = OUT / 'scope-collision'
(root / 'lib').mkdir(parents=True, exist_ok=True)
lib = 'pub fn answer() i32 { return 1 }\npub fn evaluate(answer: i32) i32 { return answer }\n'
(root / 'lib/lib.dyn').write_text(lib)
(root / 'main.dyn').write_text('use "./lib"\nfn main() { if lib.evaluate(7) != 7 { #panic("wrong answer") } }\n')
rootcase = root / 'root-case'
rootcase.mkdir(exist_ok=True)
(rootcase / 'main.dyn').write_text(lib + '\nfn main() { if evaluate(7) != 7 { #panic("wrong answer") } }\n')
result = {}
for name, path in [('imported', root), ('root', rootcase)]:
    r = subprocess.run([m.DYN, 'check', str(path), '--quiet'], capture_output=True, text=True, timeout=30)
    result[name] = {'exit': r.returncode, 'stderr': r.stderr}
(root / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
assert all(item['exit'] == 0 for item in result.values()), result
print('PASS imported parameter scope')

# Directory bytes must be escaped in protocol JSON and Dyn import strings.
root = OUT / 'lsp-quoted-path'
quoted = root / 'bad"quote'
quoted.mkdir(parents=True, exist_ok=True)
(quoted / 'lib.dyn').write_text('pub fn ZebraUnique() {}\n')
path = root / 'main.dyn'
text = 'fn main() { Zebra }'
path.write_text(text)
def completion_result():
    responses, stderr = m.run_lsp([m.opened(path, text), m.request('textDocument/completion', {
        'textDocument': {'uri': path.as_uri()}, 'position': {'line': 0, 'character': 17}}, 2)])
    return next(r for r in responses if r.get('id') == 2)
result = {'quoted': completion_result()}
quoted.rename(root / 'safe')
try:
    result['plain_control'] = completion_result()
finally:
    (root / 'safe').rename(quoted)
(root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
assert 'result' in result['quoted'], result['quoted']
print('PASS quoted path preserves completions')
assert 'result' in result['plain_control']

# Shared project overlays survive two table growths and close/reopen.
root = OUT / 'lsp-shared-overlays'
root.mkdir(exist_ok=True)
messages = []
paths = []
for i in range(65):
    path = root / f'part{i}.dyn'
    path.write_text(f'pub fn part{i}() i32 {{ return 1 }}\n')
    paths.append(path)
    messages.append(m.opened(path, f'pub fn part{i}() i32 {{ return true }}\n'))
messages.append(m.request('textDocument/didClose', {'textDocument': {'uri': paths[0].as_uri()}}))
messages.append(m.opened(paths[0], 'pub fn part0() i32 { return false }\n'))
responses, stderr = m.run_lsp(messages)
assert not stderr, stderr
for path in paths:
    assert m.diagnostics(responses, path), path
print('PASS 65 shared overlays, resize and close/reopen')

# Cached exports must yield to unsaved declarations, then disk after close.
root = OUT / 'lsp-export-overlay'
(root / 'library').mkdir(parents=True, exist_ok=True)
path = root / 'main.dyn'
text = 'fn main() { Zebra }'
path.write_text(text)
lib = root / 'library/module.dyn'
lib.write_text('pub fn ZebraDisk() {}\n')
def complete(ident):
    return m.request('textDocument/completion', {'textDocument': {'uri': path.as_uri()}, 'position': {'line': 0, 'character': 17}}, ident)
responses, stderr = m.run_lsp([m.opened(path, text), complete(2),
    m.opened(lib, 'pub fn ZebraUnsaved() {}\n'), complete(3),
    m.request('textDocument/didClose', {'textDocument': {'uri': lib.as_uri()}}), complete(4)])
assert not stderr, stderr
for ident, wanted, absent in [(2, 'ZebraDisk', 'ZebraUnsaved'), (3, 'ZebraUnsaved', 'ZebraDisk'), (4, 'ZebraDisk', 'ZebraUnsaved')]:
    result = next(r['result'] for r in responses if r.get('id') == ident)
    labels = {i['label'] for i in (result['items'] if isinstance(result, dict) else result)}
    assert wanted in labels and absent not in labels, (ident, labels)
print('PASS cached exports honor unsaved edits and close')
