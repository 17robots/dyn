from pathlib import Path
import json,subprocess,os,time,statistics,random,hashlib
W=Path(__file__).resolve().parent;R=W.parents[1];B=W.parent/'hot-inline-20261024';D=R/'build/app-comparison-20261024';want=json.loads((D/'expected.json').read_text());results={};retained=41;os.sched_setaffinity(0,{2});env=dict(os.environ,DYN_SDK=str(R));c=R/'build/faster-20261024/before/gcc-app'
for app in ['compact','mutable']:
 cases={'before':B/('final-'+app),'hint':W/('hint-'+app),'c-yyjson':c};values={x:[] for x in cases};order=[]
 for i in range(retained+2):
  names=list(cases);names=names[i%3:]+names[:i%3]
  if i%2:names.reverse()
  order.append(names)
  for name in names:
   t=time.perf_counter_ns();p=subprocess.run([str(cases[name]),'report',str(D/'events.jsonl')],env=env,capture_output=True,text=True,timeout=30);ms=(time.perf_counter_ns()-t)/1e6
   assert p.returncode==0 and not p.stderr and json.loads(p.stdout)==want['report'],(name,p)
   if i>=2:values[name].append(ms)
 ratios=[a/b for a,b in zip(values['hint'],values['before'])];rng=random.Random(20261025);boot=sorted(statistics.median(rng.choices(ratios,k=retained)) for _ in range(10000))
 results[app]={'retained_samples':retained,'warmups':2,'milliseconds':values,'median_ms':{k:statistics.median(v) for k,v in values.items()},'paired_median_ratio_95':[boot[250],boot[9749]],'order':order,'binaries':{k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in cases.items()},'input_sha256':hashlib.sha256((D/'events.jsonl').read_bytes()).hexdigest()}
 print(app,results[app]['median_ms'],results[app]['paired_median_ratio_95'],flush=True)
 (W/'app-controls.json').write_text(json.dumps(results,indent=2))
