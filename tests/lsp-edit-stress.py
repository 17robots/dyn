#!/usr/bin/env python3
"""Incremental editing must match fresh analysis, including imported overlays."""
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import tempfile

h = runpy.run_path('tests/lsp-contracts.py')
request, opened = h['request'], h['opened']
signal.alarm(90)
with tempfile.TemporaryDirectory(prefix='dyn-edit-stress-') as directory, tempfile.TemporaryFile() as errors:
    root = Path(directory)
    source = root / 'main.dyn'
    module = root / 'lib/module.dyn'
    module.parent.mkdir()
    library = 'pub const answer: i32 = 42\npub fn apple() i32 { return answer }\n'
    module.write_text(library)
    source.write_text('fn main() {}\n')
    process = subprocess.Popen([h['DYN'], 'lsp'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=errors, env=dict(os.environ, DYN_SDK=str(Path('compiler').resolve())))
    diagnostics = {}
    def send(message):
        body = json.dumps(message).encode()
        process.stdin.write(b'Content-Length: %d\r\n\r\n' % len(body) + body)
        process.stdin.flush()
    def response(ident):
        while True:
            header = process.stdout.readline()
            assert header, f'LSP exited: {process.poll()}'
            length = int(header.split(b':', 1)[1])
            assert process.stdout.readline() == b'\r\n'
            message = json.loads(process.stdout.read(length))
            if message.get('method') == 'textDocument/publishDiagnostics':
                diagnostics[message['params']['uri']] = message['params']['diagnostics']
            if message.get('id') == ident:
                assert 'error' not in message, message
                return message['result']
    def point(text):
        return {'line': text.count('\n'), 'character': len(text.rsplit('\n', 1)[-1].encode('utf-16-le')) // 2}
    cases = [
        'use "|', 'use "std/|', 'use "std/mem|',
        'use "./lib" lib\nconst value: i32 = lib.answer\nfn main() { _ = value }\n|',
        'use "./lib" lib\nconst value: bool = lib.answer\nfn main() { _ = value }\n|',
        'use "./lib" renamed\nconst value := renamed.answer\nfn main() { renamed.ap| }',
        'use "./lib"\nconst value := lib.answer\nfn main() { _ = value }\n|',
        '// 😀 byte/UTF-16 positions differ\nuse "./lib" lib\nfn main() { lib.ap| }',
        'use "./lib" lib\nconst value :=\nfn main() { lib.ap| }',
        'fn main() { const value: i32 = 1\n_ = value }\n|',
        'struct Box { value: i32 }\nfn main() { _ = Box(i32){value: 1} }\n|',
    ]
    try:
        send(request('initialize', {}, 1)); response(1)
        send(opened(source, 'fn main() {}\n'))
        previous = 'fn main() {}\n'
        ident = 10
        for cycle in range(6):
            overlay = library if cycle % 2 == 0 else library.replace('i32 = 42', 'bool = true')
            send(opened(module, overlay)) if cycle == 0 else send(request('textDocument/didChange', {
                'textDocument': {'uri': module.as_uri(), 'version': cycle + 1}, 'contentChanges': [{'text': overlay}]}))
            for marked in cases:
                before, after = marked.split('|')
                text = before + after
                # Replace through a ranged edit, exercising UTF-16 conversion and tree edits.
                send(request('textDocument/didChange', {'textDocument': {'uri': source.as_uri(), 'version': ident},
                    'contentChanges': [{'range': {'start': {'line': 0, 'character': 0}, 'end': point(previous)}, 'text': text}]}))
                previous = text
                completion = request('textDocument/completion', {'textDocument': {'uri': source.as_uri()}, 'position': point(before)}, ident)
                tokens = request('textDocument/semanticTokens/full', {'textDocument': {'uri': source.as_uri()}}, ident + 1)
                send(completion); actual_completion = response(ident)
                send(tokens); actual_tokens = response(ident + 1)
                actual_diagnostics = diagnostics.get(source.as_uri(), [])
                fresh, stderr = h['run_lsp']([opened(module, overlay), opened(source, text), completion, tokens])
                assert not stderr, stderr
                expected = {r['id']: r['result'] for r in fresh if 'id' in r}
                assert actual_completion == expected[ident], ('completion', cycle, marked)
                assert actual_tokens == expected[ident + 1], ('tokens', cycle, marked)
                assert actual_diagnostics == h['diagnostics'](fresh, source), ('diagnostics', cycle, marked, actual_diagnostics, h['diagnostics'](fresh, source))
                if marked == 'use "std/|':
                    items = actual_completion.get('items', []) if isinstance(actual_completion, dict) else actual_completion
                    assert any(i['label'] == 'mem' for i in items), items
                    assert all(not i.get('insertText', i['label']).endswith('/') for i in items), items
                ident += 2
        send(request('textDocument/didClose', {'textDocument': {'uri': module.as_uri()}}))
        send(request('shutdown', None, 999)); response(999)
        send(request('exit', None)); process.stdin.close()
        assert process.wait(timeout=5) == 0
        errors.seek(0); assert not errors.read()
    finally:
        if process.poll() is None:
            process.kill(); process.wait()
signal.alarm(0)
print('PASS 66 incremental/fresh comparisons: imports, aliases, consts, Unicode, diagnostics, completion, semantic tokens')
