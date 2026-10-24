from pathlib import Path
import os,subprocess,json,statistics,random
W=Path(__file__).resolve().parent;R=Path(os.environ.get('DYN_SOURCE_ROOT',str(W.parents[1]))).resolve();ref=json.loads((W/'normalized.json').read_text())
for name in ['gcc-checked-noalias','gcc-checked-noclone','gcc-checked-frame','gcc-checked-conservative']:
 p=subprocess.run([str(W/'driver'),str(W/(name+'.so')),'batch','1',str(W/'cases.bin')],capture_output=True,text=True,check=True,timeout=120);assert [json.loads(x) for x in p.stdout.splitlines()]==ref,name
 print('PASS full twin controls',name,flush=True)
os.sched_setaffinity(0,{2});names=['dyn','gcc-checked','gcc-checked-conservative','clang-checked'];ss={n:[] for n in names};env=dict(os.environ,LD_PRELOAD=str(W/'common-thin.so'))
for i in range(19):
 order=names[i%4:]+names[:i%4]
 if i%2:order.reverse()
 for name in order:
  p=subprocess.run([str(W/'driver'),str(W/(name+'.so')),'bench','1',str(Path(os.environ.get('JSONL_INPUT',str(R/'build/app-comparison-20261024/events.jsonl'))).resolve()),'3'],env=env,capture_output=True,text=True,check=True,timeout=30);v=json.loads(p.stdout);assert v['records']==180000 and v['checksum']==1620000 and v['primitives']==[0]*14
  if i>=2:ss[name].append(v['seconds']*1000/3)
ratio=[];rng=random.Random(20261024)
for _ in range(10000):
 ix=[rng.randrange(17) for _ in range(17)];ratio.append(statistics.median(ss['dyn'][i] for i in ix)/statistics.median(ss['gcc-checked'][i] for i in ix))
ratio.sort();r={'samples_ms_per_pass':ss,'median_ms_per_pass':{n:statistics.median(v) for n,v in ss.items()},'dyn_checked_c_ratio_95':[ratio[250],ratio[9749]],'bootstrap_resamples':10000};(W/'conservative.json').write_text(json.dumps(r,indent=2)+'\n');print(r['median_ms_per_pass'],r['dyn_checked_c_ratio_95'])
