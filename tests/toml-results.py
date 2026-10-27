#!/usr/bin/env python3
"""TOML 1.0 parser/writer checked against Python tomllib, optional toml-test corpus."""
import datetime
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import tomllib
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
CLI='''use "std/encoding/toml" toml
use "std/mem" mem
use "std/fs" fs
use "std/process" process
use "std/io" io
fn main() {
 arena := mem.Arena{}
 defer { mem.arena_release(&arena) }
 args := process.arguments(&arena)
 if !args.ok || #len(args.value) != 3 { #panic("arguments") }
 source := fs.read_all(&arena,args.value[1],16777216)
 if !source.ok { #panic("read") }
 mark := mem.arena_mark(&arena)
 parsed := toml.parse(&arena,source.value)
 if !parsed.ok {
  if mem.arena_mark(&arena) != mark { #panic("rollback") }
  _ = io.println(io.stdout(),"ERR {}",parsed.offset)
  return
 }
 encoded := toml.encode(&arena,parsed.root)
 if !encoded.ok { #panic("encode") }
 if !fs.write_all(args.value[2],encoded.value).ok { #panic("write") }
 _ = io.println(io.stdout(),"OK")
}
'''
VALID=[b'',b'x=1\n',b'''title = "TOML Example"
[owner]
name = "Tom Preston-Werner"
dob = 1979-05-27T07:32:00-08:00
[database]
enabled = true
ports = [ 8000, 8001, 8002 ]
data = [ ["delta", "phi"], [3.14] ]
temp_targets = { cpu = 79.5, case = 72.0 }
[[products]]
name = "Hammer"
[[products]]
name = "Nail"
color = "gray"
''',b'"" = ""\nx = -9223372036854775808\ny=9223372036854775807\nz=0x7fff_ffff\n',b"x = '''\nhello\nworld'''\ny=\"\"\"a\\\n  b\"\"\"\n",b'x = 2000-02-29\ny = 12:34:56.123\nz=1979-05-27 07:32:00Z\n',b'a.b.c = 1\na.d = 2\n',b'x=[1,"two",true,{a=2}]\ny=+inf\nz=-nan\n']
VALID += [b'x="\\u007f"\n',b'"\\u007f"="value"\n',b'[a.b]\nx=1\n[a]\ny=2\n',b'[[a]]\nx=1\n[a.b]\ny=2\n[[a]]\nx=3\n']
INVALID=[b'x=',b'x=1\nx=2',b'x=00',b'x=0_0',b'x=0x8000000000000000',b'x=9223372036854775808',b'x=-9223372036854775809',b'x=+0x1',b'x=1.',b'x=.1',b'x=1e',b'x=1__0',b'x={a=1,}',b'x={a=1}\nx.b=2',b'a.b=1\n[a]',b'[a]\n[a]',b'x=[1 2]',b'x="\\ q"',b'x=2001-02-29',b'x=24:00:00',b'x=2000-01-01T00:00:00+24:00',b'x="\xff"',b'#\x00',b'x="a\nb"']
INVALID += [b'x=23:59:61',b'x=1990-12-31T23:59:61Z',b'x="""bad\\ space"""',b'[a.b.c]\nx=1\n[a]\nb.c.y=2',b'x="""bad\\ \\n"""']
def equivalent(a,b):
 if isinstance(a,float) and isinstance(b,float) and math.isnan(a) and math.isnan(b):return True
 if isinstance(a,dict):return a.keys()==b.keys() and all(equivalent(a[k],b[k]) for k in a)
 if isinstance(a,list):return len(a)==len(b) and all(equivalent(x,y) for x,y in zip(a,b))
 return type(a)==type(b) and a==b
with tempfile.TemporaryDirectory(prefix='dyn-toml-') as directory:
 work=Path(directory);project=work/'project';project.mkdir();(project/'main.dyn').write_text(CLI)
 programs=[]
 for mode in ('debug','release'):
  exe=work/mode;subprocess.run([DYN,'build',str(project),'--'+mode,'--quiet','--no-cache','--output',str(exe)],check=True,timeout=300);programs.append(exe)
 cases=[(f'valid-{i}',x,True) for i,x in enumerate(VALID)]+[(f'invalid-{i}',x,False) for i,x in enumerate(INVALID)]
 corpus=os.environ.get('TOML_TEST_CORPUS')
 if corpus:
  path=Path(corpus)
  for name in (path/'files-toml-1.0.0').read_text().splitlines():
   if name.endswith('.toml'):cases.append((name,(path/name).read_bytes(),name.startswith('valid/')))
 rng=random.Random(351)
 for i in range(100):
  data=bytearray(VALID[2]);at=rng.randrange(len(data));data[at]^=1<<rng.randrange(8)
  try:tomllib.loads(data.decode());valid=True
  except (ValueError,UnicodeError):valid=False
  cases.append((f'mutation-{i}',bytes(data),valid))
 failures=[]
 for name,data,valid in cases:
  source=work/'input';source.write_bytes(data)
  for exe in programs:
   output=work/'output'
   ran=subprocess.run([str(exe),str(source),str(output)],capture_output=True,text=True,timeout=30)
   if ran.returncode or (ran.stdout.startswith('OK')!=valid):failures.append((name,exe.name,ran.stdout,ran.stderr));break
   if valid:
    try:
     expected=tomllib.loads(data.decode());actual=tomllib.loads(output.read_text())
     assert equivalent(expected,actual),(expected,actual)
    except Exception as error:failures.append((name,exe.name,str(error)));break
 # RFC 3339 lexemes beyond Python datetime's representable range. Check their
 # exact spelling separately, since tomllib rejects leap seconds and year zero.
 lexemes=[b'1990-12-31T23:59:60Z',b'1991-01-01T00:59:60.125+01:00',b'23:59:60',b'0000-01-01',b'0000-01-01T00:00:00Z']
 for lexeme in lexemes:
  source=work/'input';source.write_bytes(b'x = '+lexeme+b'\n')
  for exe in programs:
   output=work/'output'
   ran=subprocess.run([str(exe),str(source),str(output)],capture_output=True,text=True,timeout=30)
   assert ran.returncode==0 and ran.stdout.startswith('OK'),(lexeme,exe.name,ran.stdout,ran.stderr)
   assert output.read_bytes()==b'"x" = '+lexeme+b'\n',(lexeme,output.read_bytes())
   # Confirm canonical output remains parseable and preserves the same lexeme.
   again=work/'again'
   subprocess.run([str(exe),str(output),str(again)],capture_output=True,check=True,timeout=30)
   assert again.read_bytes()==output.read_bytes()
 if failures:
  for failure in failures:print(failure)
  raise SystemExit(f'{len(failures)} of {len(cases)} TOML cases failed')
 portable=work/'portable';portable.mkdir()
 probe='use "std/encoding/toml" toml\nuse "std/mem" mem\nfn main() {\n arena := mem.Arena{}\n defer { mem.arena_release(&arena) }\n source: ['+str(len(VALID[2]))+']u8 = ['+','.join(map(str,VALID[2]))+']\n parsed := toml.parse(&arena,source[..])\n if !parsed.ok { #panic("portable parse") }\n encoded := toml.encode(&arena,parsed.root)\n if !encoded.ok || !toml.parse(&arena,encoded.value).ok { #panic("portable encode") }\n cycle := toml.Value{kind:toml.Kind.Table}\n child := toml.Value{kind:toml.Kind.String,key:"x"}\n child.next = &child\n cycle.first = &child\n if toml.encode(&arena,&cycle).ok { #panic("cycle") }\n}\n'
 (portable/'main.dyn').write_text(probe)
 for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows','wasm32-wasi'):
  output=work/target
  subprocess.run([DYN,'build',str(portable),'--release','--target',target,'--quiet','--output',str(output)],check=True,timeout=300)
  command=None
  if target=='aarch64-linux' and shutil.which('qemu-aarch64'):command=['qemu-aarch64',str(output)]
  if target=='riscv64-linux' and shutil.which('qemu-riscv64'):command=['qemu-riscv64',str(output)]
  if target=='wasm32-wasi' and shutil.which('node'):
   js="const {WASI}=require('node:wasi'),fs=require('fs');(async()=>{const wasi=new WASI({version:'preview1',args:[],returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance)})().catch(e=>{console.error(e);process.exit(1)})"
   command=['node','--no-warnings','-e',js,str(output)]
  if command:subprocess.run(command,check=True,timeout=30)
 print(f'PASS TOML {len(cases)} cases + {len(lexemes)} RFC3339 lexeme cases with tomllib semantic roundtrip, malformed rollback debug/release')
