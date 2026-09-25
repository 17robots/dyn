#!/usr/bin/env python3
"""Consecutive edits coalesce; requests and partial frames preserve ordering."""
import json, os, re, signal, subprocess, tempfile
from pathlib import Path
signal.alarm(60)
DYN = str(Path(os.environ.get('DYN', 'build/dyn')).resolve())
def wire(method, params, ident=None):
    message = {'jsonrpc':'2.0', 'method':method, 'params':params}
    if ident is not None: message['id'] = ident
    body = json.dumps(message).encode()
    return b'Content-Length: %d\r\n\r\n'%len(body)+body
with tempfile.TemporaryDirectory(prefix='dyn-lsp-batch-') as directory, tempfile.TemporaryFile() as errors:
    path = Path(directory)/'main.dyn'; path.write_text('fn main() {}\n')
    process = subprocess.Popen([DYN, 'lsp'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
        env=dict(os.environ, DYN_LSP_ANALYSIS_STATS='1'))
    def send(data): process.stdin.write(data); process.stdin.flush()
    def response(ident):
        messages = []
        while True:
            header = process.stdout.readline(); assert header, process.poll()
            length = int(header.split(b':')[1]); assert process.stdout.readline() == b'\r\n'
            message = json.loads(process.stdout.read(length)); messages.append(message)
            if message.get('id') == ident: return messages
    def change(text, version):
        return wire('textDocument/didChange', {'textDocument':{'uri':path.as_uri(),'version':version},'contentChanges':[{'text':text}]})
    def barrier(ident): return wire('textDocument/documentSymbol', {'textDocument':{'uri':path.as_uri()}}, ident)
    send(wire('initialize', {}, 1)); response(1)
    send(wire('textDocument/didOpen', {'textDocument':{'uri':path.as_uri(),'text':path.read_text(),'version':1}})+barrier(2)); response(2)
    send(change('fn main( {', 2)+change('// 😀\nfn main() {}\n', 3)+barrier(3))
    messages = response(3)
    assert not [d for m in messages for d in m.get('params',{}).get('diagnostics',[])], messages
    # A partial following frame must not block publishing the completed edit.
    partial = barrier(4)
    send(change('fn renamed() {}\n', 4)+partial[:10])
    header = process.stdout.readline(); assert header
    length = int(header.split(b':')[1]); assert process.stdout.readline() == b'\r\n'
    assert json.loads(process.stdout.read(length))['method'] == 'textDocument/publishDiagnostics'
    send(partial[10:]); messages = response(4)
    assert messages[-1]['result'][0]['name'] == 'renamed', messages
    # Request between edits must observe its own revision.
    send(change('fn first() {}', 5)+barrier(5)+change('fn second() {}', 6)+barrier(6))
    assert response(5)[-1]['result'][0]['name'] == 'first'
    assert response(6)[-1]['result'][0]['name'] == 'second'
    # Malformed request envelopes must end batching too.
    malformed = json.dumps({'method':'textDocument/didChange','params':{}}).encode()
    send(change('fn after_invalid() {}', 7)+b'Content-Length: %d\r\n\r\n'%len(malformed)+malformed+barrier(7))
    messages = response(7)
    assert messages[-1]['result'][0]['name'] == 'after_invalid', messages
    error_index = next(i for i,m in enumerate(messages) if m.get('error',{}).get('code') == -32600)
    assert any(m.get('method') == 'textDocument/publishDiagnostics' for m in messages[:error_index]), messages
    send(wire('shutdown', None, 99)+wire('exit', None)); response(99)
    process.stdin.close(); assert process.wait(timeout=5) == 0
    errors.seek(0); stats = errors.read().decode()
    assert int(re.search(r'coalesced-edits=(\d+)',stats)[1]) >= 1, stats
print('PASS queued edits, partial frames, Unicode and request barriers')
