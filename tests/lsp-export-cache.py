#!/usr/bin/env python3
"""An already-running LSP must notice disk exports without watcher notifications."""
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import tempfile
h=runpy.run_path('tests/lsp-contracts.py')
signal.alarm(20)
with tempfile.TemporaryDirectory(prefix='dyn-export-cache-') as directory, tempfile.TemporaryFile() as errors:
    root=Path(directory);library=root/'library';library.mkdir()
    source=root/'main.dyn';text='fn main() { Zebra }';source.write_text(text)
    module=library/'module.dyn';module.write_text('pub fn ZebraOne() {}\n')
    process=subprocess.Popen([h['DYN'],'lsp'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,
                             env=dict(os.environ,DYN_SDK=str(Path('compiler').resolve())))
    def send(message):
        body=json.dumps(message).encode()
        process.stdin.write(b'Content-Length: %d\r\n\r\n'%len(body)+body);process.stdin.flush()
    def response(ident):
        while True:
            header=process.stdout.readline()
            assert header, f'LSP stopped: {process.poll()}'
            length=int(header.split(b':',1)[1]);assert process.stdout.readline()==b'\r\n'
            result=json.loads(process.stdout.read(length))
            if result.get('id')==ident:
                assert 'error' not in result,result
                return result['result']
    def labels(ident):
        send(h['request']('textDocument/completion',{'textDocument':{'uri':source.as_uri()},'position':{'line':0,'character':17}},ident))
        result=response(ident)
        return {item['label'] for item in (result['items'] if isinstance(result,dict) else result)}
    try:
        send(h['request']('initialize',{},1));response(1)
        send(h['opened'](source,text))
        assert 'ZebraOne' in labels(2)
        stamp=module.stat()
        module.write_text('pub fn ZebraTwo() {}\n')
        os.utime(module,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        changed=labels(3)
        assert 'ZebraTwo' in changed and 'ZebraOne' not in changed,changed
        module.unlink()
        assert 'ZebraTwo' not in labels(4)
        module.write_text('pub fn ZebraNew() {}\n')
        assert 'ZebraNew' in labels(5)
        send(h['request']('shutdown',None,999));response(999)
        send(h['request']('exit',None));process.stdin.close()
        assert process.wait(timeout=5)==0
        errors.seek(0);assert not errors.read()
    finally:
        if process.poll() is None: process.kill();process.wait()
signal.alarm(0)
print('PASS live export cache: same-size/preserved-mtime edit, delete, recreate without watchers')
