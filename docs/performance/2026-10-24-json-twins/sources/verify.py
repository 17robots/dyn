from pathlib import Path
import subprocess,os,json,random,struct,hashlib,ctypes,math,importlib.util
W=Path(__file__).resolve().parent;R=Path(os.environ.get('DYN_SOURCE_ROOT',str(W.parents[1]))).resolve()
class Pairs(list):pass
class Number:
 def __init__(self,text):self.text=text
MASK=2**64-1
def value_nodes(value,depth=0):
 if value is None:return [[f'{1:016x}',f'{0:016x}']]
 if isinstance(value,bool):return [[f'{2:016x}',f'{int(value):016x}']]
 if isinstance(value,str):
  data=value.encode('utf8');return [[f'{len(data)*256+4:016x}',data.hex()]]
 if isinstance(value,Number):
  s=value.text
  if not any(c in s for c in '.eE'):
   n=int(s)
   if not s.startswith('-') and n<=MASK:return [[f'{259:016x}',f'{n:016x}']]
   if s.startswith('-') and n!=0 and n>=-2**63:return [[f'{515:016x}',f'{n&MASK:016x}']]
  n=float(s)
  if not math.isfinite(n):raise ValueError('overflow')
  bits=struct.unpack('<Q',struct.pack('<d',n))[0];return [[f'{771:016x}',f'{bits:016x}']]
 if depth>=256:raise ValueError('depth')
 out=[]
 if isinstance(value,Pairs):
  for key,val in value:out+=value_nodes(key,depth+1)+value_nodes(val,depth+1)
  tag=len(value)*256+6
 else:
  for val in value:out+=value_nodes(val,depth+1)
  tag=len(value)*256+5
 return [[f'{tag:016x}',f'{len(out)+1:016x}']]+out
def oracle(data):
 try:
  v=json.loads(data.decode('utf8'),parse_int=Number,parse_float=Number,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)),object_pairs_hook=Pairs)
  return value_nodes(v)
 except (ValueError,UnicodeError,OverflowError,RecursionError):return None
cases=[bytes.fromhex(x) for x in json.loads((W/'cases.json').read_text())]
(W/'cases.json').write_text(json.dumps([x.hex() for x in cases])+'\n');(W/'cases.bin').write_bytes(b''.join(struct.pack('<Q',len(x))+x for x in cases))
libs=['dyn','dyn-tree','gcc','gcc-checked','gcc-scalar','gcc-checked-scalar','clang','clang-checked','gcc-noinline']
reference=None;comparisons=0
for mode in (0,1):
 for name in libs:
  p=subprocess.run([str(W/'driver'),str(W/(name+'.so')),'batch',str(mode),str(W/'cases.bin')],capture_output=True,text=True,timeout=120)
  (W/('verify-'+name+'-'+str(mode)+'.log')).write_text(p.stderr)
  assert p.returncode==0,(name,mode,p.returncode,p.stderr[-2000:])
  rows=[json.loads(x) for x in p.stdout.splitlines()];assert len(rows)==len(cases),(name,mode,len(rows))
  if reference is None:
   reference=rows;(W/'normalized.json').write_text(json.dumps(rows,separators=(',',':'))+'\n')
   for i,(raw,row) in enumerate(zip(cases,rows)):
    expected=oracle(raw);assert bool(row['ok'])==(expected is not None),(i,raw.hex(),row,expected)
    if expected is not None:assert row['nodes']==expected,(i,raw.hex(),row['nodes'],expected)
    else:assert row['arena'][0]==3 and row['used']==0 and row['retained']==0,(i,row)
  else:
   assert rows==reference,next(((i,cases[i].hex(),a,b) for i,(a,b) in enumerate(zip(rows,reference)) if a!=b),(name,mode,'rowcount'))
  comparisons+=len(rows);print('PASS full DOM/errors/arena/exact traces/primitives',name,'mode',mode,'cases',len(rows),flush=True)
# Both ABIs must agree on the five complete layouts.
lib=ctypes.CDLL(str(W/'dyn.so'));lib.twin_layout.argtypes=[ctypes.c_size_t];lib.twin_layout.restype=ctypes.c_size_t
assert [lib.twin_layout(i) for i in range(5)]==[16,64,32,88,48]
for pad in range(16):
 path=W/'alignment.json';path.write_text('{"x":["é😀",1,-0,{},true],"k":"long ascii string value"}')
 rows=[]
 for name in ['dyn','gcc-checked','clang-checked']:
  p=subprocess.run([str(W/'driver'),str(W/(name+'.so')),'inspect','1',str(path),str(pad)],capture_output=True,text=True,check=True,timeout=15);rows.append(json.loads(p.stdout))
 assert rows[0]==rows[1]==rows[2],(pad,rows)
summary={'cases':len(cases),'full_comparisons':comparisons,'libraries':libs,'modes':[0,1],'abi_sizes':[16,64,32,88,48],'misaligned_backing_offsets':16,'independent_oracle':'Python strict UTF8 JSON with lexical numbers and duplicate-preserving objects; exact normalized full DOM','case_sha256':hashlib.sha256((W/'cases.bin').read_bytes()).hexdigest()}
(W/'verification.json').write_text(json.dumps(summary,indent=2)+'\n');print('PASS',summary)
