#!/usr/bin/env python3
"""Resource diagnostics, malformed input, failed output/cache, and editor recovery."""
import json, os, resource, runpy, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
os.environ['DYN']=DYN
h=runpy.run_path(str(ROOT/'tests/lsp-contracts.py'))
def limits(): resource.setrlimit(resource.RLIMIT_CORE,(0,0))
with tempfile.TemporaryDirectory(prefix='dyn-robustness-') as directory:
    root=Path(directory); source=root/'main.dyn'; output=root/'program'
    def invoke(command='check', **kwargs):
        result=subprocess.run([DYN,command,str(root),'--quiet','--no-cache','--output',str(output)],capture_output=True,text=True,timeout=30,preexec_fn=limits,**kwargs)
        assert result.returncode in (0,1,2), (result.returncode,result.stderr)
        assert 'AddressSanitizer' not in result.stderr and 'runtime error:' not in result.stderr,result.stderr
        return result
    good='fn main() { _ = '+'('*32+'1'+')'*32+' }\n'
    source.write_text(good); assert invoke('build').returncode==0
    subprocess.run([str(output)],check=True,timeout=10)
    for tail in (')'*8192, ''):
        deep='fn main() { _ = '+'('*8192+'1'+tail+' }\n'
        source.write_text(deep)
        for command in ('check','build'):
            r=invoke(command); assert r.returncode==1 and ('syntax nesting exceeds' in r.stderr if tail else 'syntax' in r.stderr),r.stderr
        if tail:
            r=subprocess.run([DYN,'check',str(root),'--diagnostics','json'],capture_output=True,text=True,timeout=30)
            diagnostic=json.loads(r.stderr)
            assert r.returncode==1 and 'syntax nesting exceeds' in diagnostic['message'],r.stderr
        # Diagnostic survives requests; a later valid edit must fully recover.
        source.write_text(good)
        messages=[h['opened'](source,deep),h['request']('textDocument/documentSymbol',{'textDocument':{'uri':source.as_uri()}},2),h['request']('textDocument/semanticTokens/full',{'textDocument':{'uri':source.as_uri()}},3),h['request']('textDocument/hover',{'textDocument':{'uri':source.as_uri()},'position':{'line':0,'character':5}},4),h['request']('textDocument/didChange',{'textDocument':{'uri':source.as_uri(),'version':2},'contentChanges':[{'text':good}]}),h['request']('textDocument/documentSymbol',{'textDocument':{'uri':source.as_uri()}},5)]
        responses,stderr=h['run_lsp'](messages)
        assert any(('syntax nesting exceeds' in d['message'] if tail else 'syntax' in d['message']) for r in responses if r.get('method')=='textDocument/publishDiagnostics' for d in r['params']['diagnostics']),responses
        assert h['diagnostics'](responses,source)==[],responses
        assert not stderr,stderr
    for data in (b'fn main() { \xff }',b'fn main() { _ = "unterminated',b'fn main() { alias:r }'):
        source.write_bytes(data); assert invoke().returncode!=0
    source.write_text(good)
    badcache=dict(os.environ,DYN_CACHE_DIR='/dev/null/dyn-cache')
    assert invoke('build',env=badcache).returncode==0
    # Default caching must also fall back to in-memory interfaces.
    r=subprocess.run([DYN,'build',str(root),'--quiet','--output',str(output)],env=badcache,capture_output=True,text=True,timeout=30)
    assert r.returncode==0,r.stderr
    subprocess.run([str(output)],check=True,timeout=10)
    r=subprocess.run([DYN,'build',str(root),'--quiet','--no-cache','--output','/dev/null/program'],capture_output=True,text=True,timeout=30)
    assert r.returncode in (1,2),r
print('PASS nesting/resource diagnostics, malformed inputs, cache/output failure and LSP recovery')
