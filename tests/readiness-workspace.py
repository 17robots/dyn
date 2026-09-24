#!/usr/bin/env python3
"""Exercise multi-root document churn, edit recovery and long-lived LSP memory."""
import json,os,signal,statistics,subprocess,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
cycles=int(os.environ.get('DYN_WORKSPACE_CYCLES','12'))
assert 1 <= cycles <= 10000
signal.alarm(max(120,cycles*15))
def wire(method,params,ident=None):
    m={'jsonrpc':'2.0','method':method,'params':params}
    if ident is not None:m['id']=ident
    data=json.dumps(m).encode();return b'Content-Length: %d\r\n\r\n'%len(data)+data
with tempfile.TemporaryDirectory(prefix='dyn-workspace-') as directory,tempfile.TemporaryFile() as stderr:
    roots=[Path(directory)/name for name in ('one','two')]
    documents=[]
    for root in roots:
        root.mkdir();(root/'main.dyn').write_text('fn main() { _ = f0() }\n')
        for i in range(32):
            path=root/f'file{i}.dyn';text=f'fn f{i}() i32 {{ return {i} }}\n';path.write_text(text);documents.append((path,text))
    process=subprocess.Popen([DYN,'lsp'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr)
    diagnostics={};latencies=[];memory=[];ident=1
    versions={path:1 for path,text in documents}
    def send(data):process.stdin.write(data);process.stdin.flush()
    def response(wanted):
        while True:
            header=process.stdout.readline();assert header,'LSP exited before response'
            length=int(header.split(b':')[1]);assert process.stdout.readline()==b'\r\n'
            message=json.loads(process.stdout.read(length))
            if message.get('method')=='textDocument/publishDiagnostics':diagnostics[message['params']['uri']]=message['params']['diagnostics']
            if message.get('id')==wanted:
                assert 'error' not in message,message
                return message.get('result')
    def barrier(path):
        global ident
        ident+=1;send(wire('textDocument/documentSymbol',{'textDocument':{'uri':path.as_uri()}},ident));return response(ident)
    def rss():
        for line in Path(f'/proc/{process.pid}/status').read_text().splitlines():
            if line.startswith('VmRSS:'):return int(line.split()[1])
        raise AssertionError('missing RSS')
    try:
        send(wire('initialize',{'workspaceFolders':[{'uri':p.as_uri(),'name':p.name} for p in roots]},ident));response(ident)
        # Exceeds the former 32-document ceiling and exercises multiple projects.
        for path,text in documents:
            send(wire('textDocument/didOpen',{'textDocument':{'uri':path.as_uri(),'languageId':'dyn','version':1,'text':text}}))
        barrier(documents[-1][0]);memory.append(rss())
        for cycle in range(cycles):
            path,text=documents[(cycle*7)%len(documents)]
            start=time.monotonic()
            bad=text.replace('return','return true +')
            versions[path]+=1
            send(wire('textDocument/didChange',{'textDocument':{'uri':path.as_uri(),'version':versions[path]},'contentChanges':[{'text':bad}]}));barrier(path)
            assert any(d.get("severity")==1 for d in diagnostics.get(path.as_uri(),[])),(path,diagnostics)
            good='// 😀 revision\n'+text
            versions[path]+=1
            send(wire('textDocument/didChange',{'textDocument':{'uri':path.as_uri(),'version':versions[path]},'contentChanges':[{'text':good}]}));result=barrier(path)
            assert not any(d.get("severity")==1 for d in diagnostics.get(path.as_uri(),[])),diagnostics[path.as_uri()]
            assert result and result[0]['name']==f'f{(cycle*7)%32}',result
            latencies.append((time.monotonic()-start)*1000)
            send(wire('textDocument/didClose',{'textDocument':{'uri':path.as_uri()}}));barrier(documents[-1][0])
            versions[path]+=1
            send(wire('textDocument/didOpen',{'textDocument':{'uri':path.as_uri(),'version':versions[path],'text':text}}));barrier(path)
            memory.append(rss())
        assert max(memory[2:] or memory)-min(memory[2:] or memory)<64*1024,memory
        assert max(latencies)<float(os.environ.get('DYN_LSP_MAX_MS','5000')),latencies
        send(wire('shutdown',None,999999));response(999999);send(wire('exit',None));process.stdin.close();process.wait(timeout=10)
        assert process.returncode==0
        stderr.seek(0);assert not stderr.read(),'unexpected LSP stderr'
    finally:
        if process.poll() is None:process.kill();process.wait()
report=dict(documents=64,roots=2,cycles=cycles,roundtrip_pairs_ms=latencies,rss_kib=memory,median_ms=statistics.median(latencies),p95_ms=sorted(latencies)[max(0,(95*len(latencies)+99)//100-1)],max_ms=max(latencies),status='passed',scope='Edit pairs include two diagnostic/navigation barriers; RSS is process RSS, not retained heap size')
(ROOT/'build/readiness').mkdir(parents=True,exist_ok=True)
(ROOT/'build/readiness/workspace.json').write_text(json.dumps(report,indent=2)+'\n')
print(f'PASS 64-document multi-root churn: {cycles} cycles, median edit pair {report["median_ms"]:.1f} ms')
