from pathlib import Path
import json,subprocess,statistics,time,hashlib,random
W=Path(__file__).resolve().parent
cases={'Dyn before':(W/'typed-bin','allocate'),'Dyn hint':(W/'hint-bin','allocate'),'C calloc/free':(W.parent/'hot-inline-20261024/extended/c-bin','allocate'),'C arena plain':(W/'matched-c','plain'),'C arena old cleanup':(W/'matched-c','guarded'),'C arena new cleanup':(W/'matched-c-hint','guarded')}
result={'scope':'unchanged extended Dyn workload, runtime-only product change; whole-process time; CPU2; serial','warmups':2,'samples':21,'runs':{},'binaries':{k:hashlib.sha256(p.read_bytes()).hexdigest() for k,(p,_) in cases.items()}}
for rounds in [32,128]:
 n=8192;seed=912345;x=seed;expected=0
 for r in range(rounds):
  x=seed+r
  for _ in range(n*2):x=(x*1664525+1013904223)&0xffffffff;expected+=x
 expected=str(expected&((1<<64)-1))+'\n'
 values={k:[] for k in cases};order=[]
 for i in range(23):
  names=list(cases);names=names[i%len(names):]+names[:i%len(names)]
  if i%2:names.reverse()
  order.append(names)
  for name in names:
   path,mode=cases[name];t=time.perf_counter_ns();p=subprocess.run([str(path),mode,str(n),str(rounds),str(seed)],capture_output=True,text=True,timeout=30);ms=(time.perf_counter_ns()-t)/1e6
   assert p.returncode==0 and p.stdout==expected and not p.stderr,(name,p)
   if i>=2:values[name].append(ms)
 summaries={k:statistics.median(v) for k,v in values.items()}
 rng=random.Random(18475+rounds);ratios=[]
 for _ in range(10000):
  ix=[rng.randrange(21) for _ in range(21)];ratios.append(statistics.median(values['Dyn hint'][i] for i in ix)/statistics.median(values['Dyn before'][i] for i in ix))
 ratios.sort();result['runs'][str(rounds)]={'n':n,'rounds':rounds,'expected':expected,'milliseconds':values,'medians_ms':summaries,'order':order,'paired_bootstrap_ratio_95':[ratios[250],ratios[9749]]}
 print(rounds,summaries,'CI',result['runs'][str(rounds)]['paired_bootstrap_ratio_95'],flush=True)
 (W/'final-timing.json').write_text(json.dumps(result,indent=2))
