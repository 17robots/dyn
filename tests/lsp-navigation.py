#!/usr/bin/env python3
"""Exercise the shared editing contract against a real Dyn SDK."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', 'build/dyn-release' + ('.exe' if os.name == 'nt' else ''))).resolve())

def run(messages, root):
    messages = [{'jsonrpc':'2.0','id':1,'method':'initialize','params':{
        'rootUri':root.as_uri(), 'capabilities':{'general':{'positionEncodings':['utf-16']}}}},
        {'jsonrpc':'2.0','method':'initialized','params':{}}, *messages,
        {'jsonrpc':'2.0','id':999,'method':'shutdown','params':None},
        {'jsonrpc':'2.0','method':'exit','params':None}]
    wire = b''
    for message in messages:
        body = json.dumps(message).encode()
        wire += b'Content-Length: %d\r\n\r\n' % len(body) + body
    process = subprocess.run([DYN,'lsp'],input=wire,capture_output=True,timeout=30)
    if process.returncode:
        raise RuntimeError(f'{DYN} lsp exited {process.returncode}: {process.stderr.decode(errors="replace")}')
    output = process.stdout
    responses = []
    while output:
        header, output = output.split(b'\r\n\r\n',1)
        size = int(header.split(b':',1)[1])
        responses.append(json.loads(output[:size]))
        output = output[size:]
    return responses

def message(method, params, ident=None):
    result = {'jsonrpc':'2.0','method':method,'params':params}
    if ident is not None:
        result['id'] = ident
    return result

class EditorContract(unittest.TestCase):
    def test_navigation_rename_format_and_unsaved_diagnostics(self):
        with tempfile.TemporaryDirectory(prefix='dyn editor ') as directory:
            root = Path(directory).resolve()
            path = root/'main.dyn'
            source = 'fn add(left: i32, right: i32) i32 {\n    sum := left + right\n    return sum\n}\n\nfn main() {\n    result := add(20, 22)\n    if result != 42 {\n        #panic("wrong result")\n    }\n}\n'
            path.write_text(source)
            doc = {'uri':path.as_uri()}
            position = {'line':6,'character':15}
            requests = [message('textDocument/didOpen',{'textDocument':dict(doc,languageId='dyn',version=1,text=source)})]
            for ident, method, params in [
                (2,'hover',{'position':position}),
                (3,'definition',{'position':position}),
                (4,'references',{'position':position,'context':{'includeDeclaration':True}}),
                (5,'rename',{'position':position,'newName':'sum_values'}),
                (6,'completion',{'position':{'line':6,'character':17}}),
                (7,'documentSymbol',{}),
                (8,'formatting',{'options':{'tabSize':4,'insertSpaces':True}}),
                (9,'semanticTokens/full',{}),
            ]:
                requests.append(message('textDocument/'+method,dict(params,textDocument=doc),ident))
            changed = source.replace('add(20, 22)', 'add(true, 22)')
            requests.append(message('textDocument/didChange',{'textDocument':dict(doc,version=2),'contentChanges':[{'text':changed}]}))
            requests.append(message('textDocument/hover',{'textDocument':doc,'position':position},10))
            requests.append(message('textDocument/documentHighlight',{'textDocument':doc,'position':position},11))
            responses = run(requests, root)
            by_id = {r['id']:r for r in responses if 'id' in r}
            for ident in range(1,12):
                self.assertNotIn('error',by_id[ident],by_id[ident])
            self.assertTrue(by_id[2]['result'])
            self.assertTrue(by_id[3]['result'])
            self.assertGreaterEqual(len(by_id[4]['result']),2)
            edits = by_id[5]['result']['changes'][path.as_uri()]
            self.assertGreaterEqual(len(edits),2)
            self.assertTrue(all(e['newText']=='sum_values' for e in edits))
            self.assertTrue(by_id[7]['result'])
            self.assertTrue(by_id[11]['result'])
            self.assertIsInstance(by_id[8]['result'],list)
            self.assertTrue(by_id[9]['result']['data'])
            diagnostics = [r['params']['diagnostics'] for r in responses if r.get('method')=='textDocument/publishDiagnostics']
            self.assertTrue(diagnostics[-1],diagnostics)
            self.assertEqual(path.read_text(),source,'LSP must not save an unsaved buffer')

if __name__ == '__main__':
    unittest.main()
