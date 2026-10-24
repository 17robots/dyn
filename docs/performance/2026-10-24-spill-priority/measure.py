from pathlib import Path
import subprocess,os,json,time,statistics,hashlib
R=Path(__file__).resolve().parents[2];W=Path(__file__).resolve().parent;T=R/'build/json-twins-20261024';DATA=R/'build/app-comparison-20261024';OLD=R/'build/json-optimizer-fixes-20261024'
env=dict(os.environ,DYN_SDK=str(R))
for project,name,flags in [(R/'build/compact-json-20261024/app-read','compact-after',[]),(R/'tools/app-comparison','mutable-after',[]),(T/'dyn','dyn-after.so',['--shared','--link',str(T/'common.so')])]:
 subprocess.run([str(R/'build/dyn-release'),'build',str(project),'--release','--opt-level','3','--cpu','generic','--no-cache','--quiet',*flags,'--output',str(W/name)],env=env,check=True,timeout=120)
# Full exact parser state/tree/trace comparison before timings.
for mode in (0,1):
 a=subprocess.check_output([str(T/'driver'),str(T/'dyn.so'),'batch',str(mode),str(T/'cases.bin')],timeout=120)
 b=subprocess.check_output([str(T/'driver'),str(W/'dyn-after.so'),'batch',str(mode),str(T/'cases.bin')],timeout=120)
 assert a==b,mode
os.sched_setaffinity(0,{2})
results={}
bins={'compact-before':OLD/'compact-after','compact-after':W/'compact-after','mutable-before':OLD/'mutable-after','mutable-after':W/'mutable-after','c-yyjson':R/'build/faster-20261024/before/gcc-app'}
want=json.loads((DATA/'expected.json').read_text())['report'];samples={k:[] for k in bins}
for rep in range(19):
 order=list(bins);order=order[rep%len(order):]+order[:rep%len(order)]
 if rep%2:order.reverse()
 for name in order:
  start=time.perf_counter();p=subprocess.run([str(bins[name]),'report',str(DATA/'events.jsonl')],env=env,capture_output=True,check=True,timeout=15);elapsed=time.perf_counter()-start
  assert json.loads(p.stdout)==want
  if rep>=2:samples[name].append(elapsed*1000)
results['apps']={'samples_ms':samples,'median_ms':{k:statistics.median(v) for k,v in samples.items()}}
print('APPS',results['apps']['median_ms'],flush=True)
libs={'before':T/'dyn.so','after':W/'dyn-after.so','checked-c':T/'gcc-checked.so'};samples={k:[] for k in libs};thin=dict(env,LD_PRELOAD=str(T/'common-thin.so'))
for rep in range(19):
 order=list(libs);order=order[rep%len(order):]+order[:rep%len(order)]
 if rep%2:order.reverse()
 for name in order:
  p=subprocess.run([str(T/'driver'),str(libs[name]),'bench','1',str(T/'events.jsonl'),'3'],env=thin,capture_output=True,text=True,check=True,timeout=30);v=json.loads(p.stdout)
  assert v['records']==180000 and v['checksum']==1620000
  if rep>=2:samples[name].append(v['seconds']*1000/3)
results['twins']={'samples_ms':samples,'median_ms':{k:statistics.median(v) for k,v in samples.items()}}
print('TWINS',results['twins']['median_ms'],flush=True)
results['search']={}
for label,folder,want in [('large',DATA/'documents',json.loads((DATA/'expected.json').read_text())['search']),('project',DATA/'project-snapshot',json.loads((DATA/'project-search.json').read_text())['expected'])]:
 samples={k:[] for k in ('mutable-before','mutable-after','c-yyjson')}
 for rep in range(43):
  order=list(samples);order=order[rep%3:]+order[:rep%3]
  if rep%2:order.reverse()
  for name in order:
   start=time.perf_counter();p=subprocess.run([str(bins[name]),'search',str(folder)],env=env,capture_output=True,check=True,timeout=15);elapsed=time.perf_counter()-start
   assert json.loads(p.stdout)==want
   if rep>=2:samples[name].append(elapsed*1000)
 results['search'][label]={'samples_ms':samples,'median_ms':{k:statistics.median(v) for k,v in samples.items()}}
 print('SEARCH',label,results['search'][label]['median_ms'],flush=True)
results['binary_hashes']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*bins.values(),*libs.values(),R/'build/dyn-release',T/'common-thin.so',T/'driver']}
(W/'final-timing.json').write_text(json.dumps(results,indent=2)+'\n')
