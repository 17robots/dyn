#!/usr/bin/env python3
"""Bound hostile-but-valid work, cancel exact request IDs, and recover cleanly."""
import json, os, runpy, signal, subprocess, tempfile, time
signal.alarm(90)
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
os.environ['DYN']=DYN
h=runpy.run_path(str(ROOT/'tests/lsp-contracts.py'))
with tempfile.TemporaryDirectory(prefix='dyn-work-budget-') as directory:
    root=Path(directory); source=root/'main.dyn'
    # A wide dependency graph has shallow syntax but consumes substantial work.
    imports=[]; calls=[]
    for i in range(96):
        module=root/f'm{i}';module.mkdir();(module/'module.dyn').write_text('pub fn value() i32 { return 1 }\n')
        imports.append(f'use "./m{i}" m{i}');calls.append(f'_ = m{i}.value()')
    text='\n'.join(imports)+'\nfn main() { '+' '.join(calls)+' }\n'
    source.write_text(text)
    r=subprocess.run([DYN,'check',str(root),'--no-cache','--max-work','1000','--diagnostics','json'],capture_output=True,text=True,timeout=10)
    errors=[json.loads(line) for line in r.stderr.splitlines()]
    assert r.returncode in (1,2) and errors and all('budget exceeded' in e['message'] for e in errors),r.stderr
    subprocess.run([DYN,'check',str(root),'--no-cache','--quiet','--max-work','10000000'],check=True,timeout=30)
    # Interrupt at progressively later compiler stages, including partial AST
    # and semantic work. Never emit unrelated partial-analysis diagnostics.
    for limit in (2000, 5000, 10000, 20000, 40000, 80000, 160000):
        r=subprocess.run([DYN,'check',str(root),'--no-cache','--max-work',str(limit),'--diagnostics','json'],capture_output=True,text=True,timeout=30)
        assert r.returncode in (0,1), (limit,r.returncode,r.stderr)
        if r.returncode:
            errors=[json.loads(line) for line in r.stderr.splitlines()]
            assert errors and all('budget exceeded' in e['message'] for e in errors),(limit,r.stderr)

    for invalid in ('0','-1','no','18446744073709551616'):
        r=subprocess.run([DYN,'check',str(root),'--max-work',invalid],capture_output=True,text=True)
        assert r.returncode==2 and '--max-work' in r.stderr,r.stderr
    # Dependency depth is independent of syntax depth. Fail with a diagnostic,
    # then prove the same process/toolchain can still analyze ordinary input.
    for i in range(260):
        module=root/f'deep{i}';module.mkdir()
        (module/'module.dyn').write_text((f'use "../deep{i+1}" next\n' if i<259 else '')+'pub fn value() i32 { return 1 }\n')
    source.write_text('use "./deep0"\nfn main() {}\n')
    r=subprocess.run([DYN,'check',str(root),'--quiet','--no-cache'],capture_output=True,text=True,timeout=30)
    assert r.returncode==1 and 'module dependency depth exceeds 256' in r.stderr,r.stderr
    source.write_text('\n'.join(f'const G{i}: i64 = G{i+1}' for i in range(600))+'\nconst G600: i64 = 42\nfn main() {}\n')
    r=subprocess.run([DYN,'check',str(root),'--quiet','--no-cache'],capture_output=True,text=True,timeout=30)
    assert r.returncode==1 and 'initializer dependency depth exceeds 512' in r.stderr,r.stderr
    good='fn value() i32 { return 42 }\nfn main() { _ = value() }\n'
    source.write_text(good)
    params={'textDocument':{'uri':source.as_uri()},'position':{'line':1,'character':18}}
    for ident in (2,'cancel-me','escaped-id'):
        request=h['request']('textDocument/hover',params,ident)
        cancel=h['request']('$/cancelRequest',{'id':ident})
        if ident=='escaped-id': cancel=b'{"jsonrpc":"2.0","method":"$/cancelRequest","params":{"id":"escaped-\\u0069d"}}'
        messages=[h['opened'](source,good),request,cancel,h['request']('textDocument/hover',params,3)]
        responses,stderr=h['run_lsp'](messages)
        stopped=[r for r in responses if r.get('id')==ident]
        assert len(stopped)==1 and stopped[0]['error']['code']==-32800, responses
        recovered=[r for r in responses if r.get('id')==3]
        assert len(recovered)==1 and 'error' not in recovered[0] and recovered[0]['result'], responses
        assert not stderr,stderr
    # Cancellation arrives after dispatch, while a changed dependency is read
    # and parsed. This exercises polling rather than only prequeued messages.
    library=root/'live';library.mkdir();module=library/'module.dyn'
    module.write_text('pub fn value() i32 { return 42 }\n')
    active='use "./live"\nfn main() { _ = live.value() }\n'
    source.write_text(active)
    live_params={'textDocument':{'uri':source.as_uri()},'position':{'line':1,'character':22}}
    with tempfile.TemporaryFile() as errors:
        process=subprocess.Popen([DYN,'lsp'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors)
        def send(message):
            data=json.dumps(message).encode()
            process.stdin.write(b'Content-Length: %d\r\n\r\n'%len(data)+data);process.stdin.flush()
        def response(ident):
            while True:
                line=process.stdout.readline();assert line,process.poll()
                length=int(line.split(b':')[1]);assert process.stdout.readline()==b'\r\n'
                result=json.loads(process.stdout.read(length))
                if result.get('id')==ident:return result
        try:
            send(h['request']('initialize',{},1));response(1)
            send(h['opened'](source,active));send(h['request']('textDocument/hover',live_params,2))
            assert response(2).get('result')
            module.write_text('pub fn value() i32 { return 42 }\n'+''.join(f'pub fn work{i}() i32 {{ return {i} }}\n' for i in range(30000)))
            started=time.monotonic();send(h['request']('textDocument/hover',live_params,3))
            time.sleep(.01);send(h['request']('$/cancelRequest',{'id':3}))
            stopped=response(3)
            assert stopped.get('error',{}).get('code')==-32800,stopped
            assert time.monotonic()-started<3
            module.write_text('pub fn value() i32 { return 42 }\n')
            send(h['request']('textDocument/hover',live_params,4));assert response(4).get('result')
            send(h['request']('shutdown',None,5));response(5);send(h['request']('exit',None))
            process.wait(timeout=5);assert process.returncode==0
            errors.seek(0);assert not errors.read()
        finally:
            if process.poll() is None:process.kill();process.wait()
    large='fn main() { '+ '_ = 1 '*10000+'}\n'
    original=os.environ.get('DYN_LSP_MAX_WORK')
    os.environ['DYN_LSP_MAX_WORK']='5000'
    start=time.monotonic()
    responses,stderr=h['run_lsp']([h['opened'](source,large),h['request']('textDocument/hover',params,2),
        h['request']('textDocument/didChange',{'textDocument':{'uri':source.as_uri(),'version':2},'contentChanges':[{'text':good}]}),h['request']('textDocument/hover',params,3)])
    assert time.monotonic()-start < 5
    assert any('budget exceeded' in d['message'].lower() for r in responses if r.get('method')=='textDocument/publishDiagnostics' for d in r['params']['diagnostics']),responses
    assert any(r.get('id')==2 and r.get('error',{}).get('code')==-32803 for r in responses),responses
    assert any(r.get('id')==3 and r.get('result') for r in responses),responses
    assert not stderr,stderr
    if original is None: os.environ.pop('DYN_LSP_MAX_WORK')
    else: os.environ['DYN_LSP_MAX_WORK']=original
print('PASS bounded dependency graph, CLI limits, numeric/string cancellation, and editor recovery')
