from pathlib import Path
import json,struct,subprocess,hashlib,os
W=Path(__file__).resolve().parent;R=Path(os.environ.get('DYN_SOURCE_ROOT',str(W.parents[1]))).resolve();data=Path(os.environ.get('JSONL_INPUT',str(R/'build/app-comparison-20261024/events.jsonl'))).resolve();lines=[x for x in data.read_bytes().split(b'\n') if x];assert len(lines)==60000
batch=W/'corpus.bin';batch.write_bytes(b''.join(struct.pack('<Q',len(x))+x for x in lines));reference=None
for name,mode in [('gcc-checked',0),('dyn',0),('gcc-checked',1),('dyn',1)]:
 out=W/('corpus-'+name+'-'+str(mode)+'.jsonl')
 with out.open('w') as f:
  p=subprocess.run([str(W/'driver'),str(W/(name+'.so')),'batch',str(mode),str(batch)],stdout=f,stderr=subprocess.PIPE,text=True,timeout=120);assert p.returncode==0,p.stderr
 if reference is None:
  reference=out
  with out.open() as f:
   for raw,normalized in zip(lines,f):
    row=json.loads(normalized);assert row['ok'] and row['used']==25 and row['nodes'][0][0]=='0000000000000906'
 else:
  with reference.open() as a,out.open() as b:
   for i,(x,y) in enumerate(zip(a,b)):
    assert x==y,(name,mode,i,x[:100],y[:100])
  assert out.stat().st_size==reference.stat().st_size
 print('PASS entire fixed corpus exact normalized DOM, traces and helper calls',name,mode,flush=True)
summary={'records':len(lines),'nodes_per_record':25,'modes':[0,1],'libraries':['gcc-checked','dyn'],'normalized_sha256':hashlib.sha256(reference.read_bytes()).hexdigest(),'input_sha256':hashlib.sha256(data.read_bytes()).hexdigest()};(W/'corpus-verification.json').write_text(json.dumps(summary,indent=2)+'\n')
