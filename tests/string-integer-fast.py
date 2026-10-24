#!/usr/bin/env python3
"""Independent bigint digit/boundary oracle for integer parsing, bases2..36."""
import os,random,struct,subprocess,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[1];DYN=str(Path(os.environ.get('DYN',R/'build/dyn-release')).resolve())
TYPES=[(f'{s}{w}',w,s=='i') for w in (8,16,32,64) for s in ('u','i')]+[('usize',struct.calcsize('P')*8,False),('isize',struct.calcsize('P')*8,True)]
def digits(n,b):
 sign='-' if n<0 else '';n=abs(n);out=''
 while n:out='0123456789abcdefghijklmnopqrstuvwxyz'[n%b]+out;n//=b
 return sign+(out or '0')
header='''use "std/strings"
use "std/fs"
use "std/mem"
fn require(ok: bool) { if !ok { #panic("integer parsing oracle") } }
fn word(data: []const u8, at: *usize) u64 {
 result: u64
 for i in 0..8 { result |= #cast(u64,data[at.*]) << #cast(u64,i*8)\n at.* += 1 }
 return result
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-string-integers-') as tmp:
 p=Path(tmp);functions=[];calls=[];count=0
 for name,width,signed in TYPES:
  low=-(1<<(width-1)) if signed else 0;high=(1<<(width-int(signed)))-1;rows=[];rng=random.Random(913+width+signed)
  for base in range(2,37):
   values={0,1,2,low,high,low-1,high+1,(1<<64)-1,1<<64,high-1}
   power=1
   while power<=1<<(width+2):
    values.update((power-1,power,power+1,-power-1,-power,-power+1));power*=base
   values.update(rng.randint(low,high) for _ in range(50))
   for value in sorted(values):
    text=digits(value,base)
    for text in (text,text.upper(),('+'+text if value>=0 else text),('000'+text if value>=0 else '-000'+text[1:])):
     valid=low<=value<=high and not(not signed and text.startswith('-'))
     rows.append((base,text.encode(),value if valid else 0,valid))
   for text in ('','+','-','-0','0x10',' 1','1 ','1_0','1.0','1e2','z'*90,'0'*100+'1','0'*100+'0'):
    try:
     valid=bool(text) and all(c.lower() in '0123456789abcdefghijklmnopqrstuvwxyz'[:base] for c in text.lstrip('+-')) and bool(text.lstrip('+-')) and (text[0]!='-' or signed)
     value=int(text,base) if valid else 0;valid=valid and low<=value<=high
    except ValueError:valid=False;value=0
    rows.append((base,text.encode(),value if valid else 0,valid))
  # Invalid radix must return zero before arithmetic.
  rows.extend((b,b'123',0,False) for b in (0,1,37,255))
  fixture=p/(name+'.bin')
  with fixture.open('wb') as f:
   for base,text,value,valid in rows:f.write(struct.pack('<QQQQ',base,len(text),value&((1<<64)-1),valid));f.write(text)
  fn='test_'+name
  functions.append(f'''fn {fn}(data: []const u8) {{
 at: usize
 for at < #len(data) {{
  base := #cast(u8,word(data,&at))
  length := #cast(usize,word(data,&at))
  expected := #cast({name},word(data,&at))
  valid := word(data,&at) != 0
  text := data[at..at+length]
  at += length
  require(strings.parse_base({name},text,base) == expected)
  if base == 10 {{ require(strings.valid({name},text) == valid)\n   require(strings.parse({name},text) == expected) }}
 }}
}}
''')
  calls.append(f'if true {{ arena := mem.arena_create(16*mem.MiB)\n input := fs.read_all(&arena,"{fixture}",16*mem.MiB)\n require(input.ok)\n {fn}(input.value)\n mem.arena_release(&arena) }}');count+=len(rows)
 (p/'main.dyn').write_text(header+'\n'.join(functions)+'\nfn main() {\n'+'\n'.join(calls)+'\n}\n')
 for mode in ('debug','release'):
  binary=p/mode;subprocess.run([DYN,'build',str(p),'--'+mode,'--no-cache','--quiet','--output',str(binary)],check=True,timeout=120)
  subprocess.run([str(binary)],check=True,timeout=60);print(f'PASS integer parsing {mode}: {count} independent base/boundary vectors')
