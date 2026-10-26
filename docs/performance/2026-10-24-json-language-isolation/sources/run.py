from pathlib import Path
import subprocess,os,json,statistics,struct,hashlib,random
W=Path(__file__).resolve().parent;R=W.parents[1];source=R/'build/app-comparison-20261024/events.jsonl';data=source.read_bytes();os.sched_setaffinity(0,{2})
records=b''.join(struct.pack('<QQ',i%7,i%1001) for i in range(1000000));(W/'records.bin').write_bytes(records)
rounds={'scan':10,'integers':5,'records':20,'parse_lines':5}
expected={'scan':sum(b in (34,92) or b<32 for b in data)*10,'records':sum(i%1001 for i in range(1000000) if i%7==3)*20,'parse_lines':sum(len(json.loads(line)) for line in data.splitlines() if line.strip())*5}
value=total=0
for b in data:
 if 48<=b<=57:
  value=value*10+b-48
  assert value<2**64
 else:total+=value;value=0
expected['integers']=(total+value)*5
samples={k:{v:[] for v in ('dyn','dyn-wrap','c','c-scalar','c-checked')} for k in rounds}
for k,n in rounds.items():
 for rep in range(11):
  names=list(samples[k]);names=names[rep%len(names):]+names[:rep%len(names)]
  if rep%2:names.reverse()
  for name in names:
   p=subprocess.run([str(W/'harness'),str(W/(name+'.so')),k,str(W/'records.bin' if k=='records' else source),str(n)],capture_output=True,text=True,timeout=15,check=True)
   checksum,seconds=p.stdout.split();assert int(checksum)==expected[k],(k,name,p.stdout,expected[k])
   if rep>=2:samples[k][name].append(float(seconds)*1000)
 med={name:statistics.median(v) for name,v in samples[k].items()};print(k,med,flush=True)
 result={'samples_ms':samples,'median_ms':{k:{n:statistics.median(v) if v else None for n,v in vs.items()} for k,vs in samples.items()},'expected':expected,'rounds':rounds,'hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [W/'dyn.so',W/'c.so',W/'c-scalar.so',source]}}
 (W/'results.json').write_text(json.dumps(result,indent=2)+'\n')
