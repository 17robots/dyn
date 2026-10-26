from pathlib import Path
import subprocess,os,time,json,statistics
W=Path(__file__).resolve().parent;R=W.parents[1];os.sched_setaffinity(0,{2});samples={n:[] for n in ('dyn-driver','c-driver')}
for i in range(13):
 for n in (list(samples) if i%2 else list(reversed(samples))):
  p=subprocess.run([str(W/'harness'),str(W/(n+'.so')),'parse_driver',str(R/'build/app-comparison-20261024/events.jsonl'),'5'],capture_output=True,text=True,timeout=15,check=True)
  v,t=p.stdout.split();assert int(v)==2700000,p.stdout
  if i>=2:samples[n].append(float(t)*1000)
result={'samples_ms':samples,'median_ms':{n:statistics.median(v) for n,v in samples.items()},'records_per_call':60000,'rounds':5,'checksum':2700000}
(W/'driver-results.json').write_text(json.dumps(result,indent=2)+'\n');print(result['median_ms'])
