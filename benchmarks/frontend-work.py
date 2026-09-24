#!/usr/bin/env python3
"""Cold no-cache builds and serialized edit-to-diagnostic latency."""
import json, os, statistics, subprocess, tempfile, time
from pathlib import Path
DYN = str(Path(os.environ.get('DYN', 'build/dyn')).resolve())
def encoded(message):
    body = json.dumps(message).encode()
    return b'Content-Length: %d\r\n\r\n' % len(body) + body
def send(process, message):
    process.stdin.write(encoded(message)); process.stdin.flush()
def receive(process):
    header = process.stdout.readline()
    if not header: raise RuntimeError(process.stderr.read().decode())
    length = int(header.split(b':')[1])
    assert process.stdout.readline() == b'\r\n'
    return json.loads(process.stdout.read(length))
with tempfile.TemporaryDirectory(prefix='dyn-work-bench-') as directory:
    root = Path(directory); (root/'lib').mkdir()
    (root/'lib/module.dyn').write_text('pub fn answer() i32 { return 42 }\n' + ''.join(
        f'pub fn helper{i}() i32 {{ x := {i} return x + 1 }}\n' for i in range(300)))
    path = root/'main.dyn'; text = 'use "./lib"\nfn main() { value := lib.answer() _ = value }\n'; path.write_text(text)
    cold = []
    for _ in range(3):
        start = time.monotonic()
        subprocess.run([DYN, 'build', str(root), '--no-cache', '--no-link', '--quiet', '--output', str(root/'main.o')], check=True, capture_output=True)
        cold.append(time.monotonic()-start)
    linked = []
    for _ in range(3):
        start = time.monotonic()
        subprocess.run([DYN, 'build', str(root), '--no-cache', '--quiet', '--output', str(root/'program')], check=True, capture_output=True)
        linked.append(time.monotonic()-start)
    process = subprocess.Popen([DYN, 'lsp'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    send(process, {'jsonrpc':'2.0','id':1,'method':'initialize','params':{}}); receive(process)
    send(process, {'jsonrpc':'2.0','method':'textDocument/didOpen','params':{'textDocument':{'uri':path.as_uri(),'languageId':'dyn','version':1,'text':text}}})
    send(process, {'jsonrpc':'2.0','id':2,'method':'textDocument/documentSymbol','params':{'textDocument':{'uri':path.as_uri()}}})
    while receive(process).get('id') != 2: pass
    edits = []
    for version in range(2,22):
        start = time.monotonic()
        send(process, {'jsonrpc':'2.0','method':'textDocument/didChange','params':{'textDocument':{'uri':path.as_uri(),'version':version},'contentChanges':[{'text':text+f'// edit {version}\n'}]}})
        send(process, {'jsonrpc':'2.0','id':version+2,'method':'textDocument/documentSymbol','params':{'textDocument':{'uri':path.as_uri()}}})
        while receive(process).get('id') != version+2: pass
        edits.append(time.monotonic()-start)
    bursts = []
    for batch in range(20):
        messages = [{'jsonrpc':'2.0','method':'textDocument/didChange','params':{
            'textDocument':{'uri':path.as_uri(),'version':100+batch*10+change},
            'contentChanges':[{'text':text+f'// burst {batch} change {change}\n'}]}}
            for change in range(10)]
        ident = 2000 + batch
        messages.append({'jsonrpc':'2.0','id':ident,'method':'textDocument/documentSymbol',
                         'params':{'textDocument':{'uri':path.as_uri()}}})
        start = time.monotonic()
        process.stdin.write(b''.join(encoded(message) for message in messages)); process.stdin.flush()
        while receive(process).get('id') != ident: pass
        bursts.append(time.monotonic()-start)
    send(process, {'jsonrpc':'2.0','id':999,'method':'shutdown','params':None}); receive(process)
    send(process, {'jsonrpc':'2.0','method':'exit','params':None}); process.stdin.close(); process.wait(timeout=5)
    assert process.returncode == 0, process.stderr.read().decode()
    print(json.dumps({'cold_build_seconds':cold,'cold_build_median':statistics.median(cold),
                      'cold_linked_build_seconds':linked,'cold_linked_build_median':statistics.median(linked),
                      'burst_seconds':bursts, 'burst_median':statistics.median(bursts),
                      'edit_diagnostic_seconds':edits,'edit_diagnostic_median':statistics.median(edits)}))
