from pathlib import Path
import subprocess,os,json,statistics,hashlib
W=Path(__file__).resolve().parent;R=Path(os.environ.get('DYN_SOURCE_ROOT',str(W.parents[1]))).resolve();input=Path(os.environ.get('JSONL_INPUT',str(R/'build/app-comparison-20261024/events.jsonl'))).resolve();os.sched_setaffinity(0,{2});rounds=3
names=['dyn','gcc','gcc-checked','gcc-checked-scalar','clang','clang-checked','gcc-checked-noalias','gcc-checked-noclone','gcc-checked-frame']
results={}
for label,mode,thin in [('scalar-thin',0,True),('sse2-thin',1,True),('sse2-traced',1,False)]:
 samples={n:[] for n in names};stats=None
 env=dict(os.environ)
 if thin:env['LD_PRELOAD']=str(W/'common-thin.so')
 else:env.pop('LD_PRELOAD',None)
 for rep in range(15):
  order=names[rep%len(names):]+names[:rep%len(names)]
  if rep%2:order.reverse()
  for name in order:
   p=subprocess.run([str(W/'driver'),str(W/(name+'.so')),'bench',str(mode),str(input),str(rounds)],env=env,capture_output=True,text=True,check=True,timeout=30);v=json.loads(p.stdout)
   assert v['records']==60000*rounds and v['checksum']==540000*rounds,(name,label,v)
   if stats is None:stats=v['primitives']
   else:assert v['primitives']==stats,(name,label,'different work',stats,v['primitives'])
   if rep>=2:samples[name].append(v['seconds']*1000/rounds)
 med={n:statistics.median(v) for n,v in samples.items()};print(label,med,flush=True);results[label]={'samples_ms_per_pass':samples,'median_ms_per_pass':med,'rounds_per_sample':rounds,'primitive_counts_per_sample':stats}
 (W/'measurements.json').write_text(json.dumps(results,indent=2)+'\n')
(W/'timed-binary-hashes.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [*(W/(n+'.so') for n in names),W/'common.so',W/'common-thin.so',W/'driver',R/'build/dyn-release']},indent=2)+'\n')
