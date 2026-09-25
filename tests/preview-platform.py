#!/usr/bin/env python3
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlsplit, parse_qs
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn')).resolve())
spec=importlib.util.spec_from_file_location('sandbox',ROOT/'compiler/tools/dyn-sandbox.py')
sandbox=importlib.util.module_from_spec(spec);spec.loader.exec_module(sandbox)

class Preview(unittest.TestCase):
    def run_code(self,source,**kwargs):
        return sandbox.run_source(source,DYN,ROOT/'compiler',ROOT/'build',**kwargs)
    def test_sandbox(self):
        report=self.run_code('fn main() { if #syscall(41,2,1,0) >= 0 { #panic("network allowed") } if #syscall(57) >= 0 { #panic("fork allowed") } }')
        self.assertEqual(report['compile']['exit_code'],0,report)
        self.assertEqual(report['run']['exit_code'],0,report)
        with tempfile.TemporaryDirectory() as directory:
            secret=Path(directory)/'secret';secret.write_text('hidden')
            data=','.join(str(b) for b in str(secret).encode())+',0'
            source=f'fn main() {{ path:[{len(str(secret).encode())+1}]u8=[{data}] if #syscall(257,-100,&path[0],0,0)>=0 {{ #panic("host file visible") }} }}'
            report=self.run_code(source)
            self.assertEqual(report['run']['exit_code'],0,report)
        timed=self.run_code('fn main() { for {} }',run_timeout=0.3)
        self.assertEqual(timed['run']['limit'],'timeout',timed)
        output=self.run_code('use "std/io"\nuse "std/terminal"\nfn main() { for { _=io.println(terminal.stdout(),"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx") } }')
        self.assertEqual(output['run']['limit'],'output-limit',output)
    def test_capability(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'root').mkdir()
            (root/'root/ok').write_text('yes');(root/'secret').write_text('hidden')
            (root/'root/link').symlink_to(root/'secret')
            (root/'main.dyn').write_text('''use "std/fs/capability" cap
fn expect(ok:bool) { if !ok { #panic("capability") } }
fn main() {
  path:[5]u8=['r','o','o','t',0]
  fd:=#syscall(257,-100,&path[0],65536,0) expect(fd>=0)
  defer { _=#syscall(3,fd) }
  directory:=cap.Directory{descriptor:fd} output:[16]u8=[]
  case cap.read(&directory,"ok",output[..]) {
    cap.ReadResult.Read count => { expect(count==3 && output[0]=='y') },
    cap.ReadResult.Failed initial_error => { _=initial_error #panic("allowed read failed") },
  }
  case cap.read(&directory,"../secret",output[..]) {
    cap.ReadResult.Read parent_count => { _=parent_count #panic("parent escaped") }, cap.ReadResult.Failed parent_error => { _=parent_error },
  }
  case cap.read(&directory,"link",output[..]) {
    cap.ReadResult.Read link_count => { _=link_count #panic("symlink escaped") }, cap.ReadResult.Failed link_error => { _=link_error },
  }
}''')
            for mode in ([],['--release']):
                subprocess.run([DYN,'build',directory,'--no-cache','--quiet','--output',str(root/'program'),*mode],check=True)
                subprocess.run([str(root/'program')],cwd=root,check=True,timeout=5)
    def test_observe(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode in ([],['--release']):
                program=str(Path(directory)/'program')
                subprocess.run([DYN,'build',str(ROOT/'tests/sdk-observe'),'--no-cache','--quiet','--output',program,*mode],check=True)
                subprocess.run([program],check=True,timeout=5)
    def test_installed_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix=Path(directory)
            (prefix/'bin').mkdir();(prefix/'lib/dyn').mkdir(parents=True)
            shutil.copy2(DYN,prefix/'bin/dyn')
            shutil.copy2(ROOT/'compiler/tools/dyn-sandbox.py',prefix/'bin/dyn-sandbox')
            shutil.copytree(ROOT/'compiler/std',prefix/'share/dyn')
            for runtime in (ROOT/'build').glob('dynrt_*.o'):
                shutil.copy2(runtime,prefix/'lib/dyn'/runtime.name)
            source=prefix/'main.dyn';source.write_text('use "std/io"\nuse "std/terminal"\nfn main() { _=io.println(terminal.stdout(),"installed") }')
            env=dict(os.environ);env.pop('DYN_SDK',None);env.pop('DYN',None)
            result=subprocess.run(['python3',str(prefix/'bin/dyn-sandbox'),str(source)],env=env,cwd=prefix,capture_output=True,text=True,check=True)
            report=json.loads(result.stdout);self.assertEqual(report['run']['stdout'],'installed\n')
            source.write_text('use "std/mem"\nfn main() { backing:[32]u8=[] arena:=mem.arena_from_buffer(backing[..]) pointer:=mem.arena_push(&arena,1,1) mem.arena_reset(&arena) pointer.*=1 }')
            invalid=subprocess.run([str(prefix/'bin/dyn'),'check',str(prefix),'--no-cache'],env=env,capture_output=True,text=True)
            self.assertNotEqual(invalid.returncode,0);self.assertIn('after arena_reset',invalid.stderr)

    def test_playground(self):
        server=subprocess.Popen(['python3',str(ROOT/'playground/server.py'),'--port','0','--dyn',DYN],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            address=server.stdout.readline().strip().split(' ',2)[-1]
            parsed=urlsplit(address);base=f'http://{parsed.netloc}'
            token=parse_qs(parsed.fragment)['token'][0]
            with urlopen(base,timeout=5) as response:
                self.assertEqual(response.status,200)
            def post(body,headers=None):
                return urlopen(Request(base+'/run',data=json.dumps(body).encode(),headers={'Content-Type':'application/json',**(headers or {})}),timeout=30)
            with self.assertRaises(HTTPError) as denied: post({'source':'fn main() {}'})
            self.assertEqual(denied.exception.code,403);denied.exception.close()
            with self.assertRaises(HTTPError) as wrong_origin: post({'source':'fn main() {}'},{'X-Dyn-Token':token,'Origin':'https://example.invalid'})
            self.assertEqual(wrong_origin.exception.code,403);wrong_origin.exception.close()
            with self.assertRaises(HTTPError) as malformed: post([],{'X-Dyn-Token':token})
            self.assertEqual(malformed.exception.code,400);malformed.exception.close()
            with post({'source':'fn main() {}'},{'X-Dyn-Token':token,'Origin':base}) as response:
                report=json.load(response)
                self.assertEqual(report['compile']['exit_code'],0,report)
                self.assertEqual(report['run']['exit_code'],0,report)
        finally:
            server.terminate();server.communicate(timeout=5)

    def test_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);module=root/'module';module.mkdir()
            source=module/'main.dyn';source.write_text('fn twice(x:i32) i32 { return x*2 } fn main() { _=twice(3) }')
            tool=str(ROOT/'compiler/tools/dyn-query.py');db=root/'program.sqlite'
            subprocess.run(['python3',tool,'--dyn',DYN,'build',str(module),'--output',str(db)],check=True,capture_output=True)
            result=subprocess.run(['python3',tool,'callers',str(db),'twice'],check=True,capture_output=True,text=True)
            rows=json.loads(result.stdout);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['caller'],'main')
            source.write_text(source.read_text()+'\n')
            stale=subprocess.run(['python3',tool,'symbol',str(db),'twice'],capture_output=True,text=True)
            self.assertNotEqual(stale.returncode,0);self.assertIn('stale database',stale.stderr)

if __name__=='__main__': unittest.main()
