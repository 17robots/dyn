#!/usr/bin/env python3
"""Measure the same search app ports against a snapshot of compiler/std sources.
Run run.py first. Original files are not modified. Results retain every hash.
"""
from pathlib import Path
import hashlib,json,os,shutil,statistics,subprocess,sys,signal
R=Path(__file__).resolve().parents[2];W=R/'build/app-comparison-20261024';tree=W/'project-snapshot'
if tree.exists():shutil.rmtree(tree)
expected=dict(files=0,bytes=0,lines=0,matching_lines=0,matching_files=0);manifest={}
for dirname in ('src','std'):
 for p in sorted((R/dirname).rglob('*')):
  if not p.is_file() or p.suffix not in ('.dyn','.c','.h','.inc'):continue
  data=p.read_bytes();rel=p.relative_to(R);target=tree/(str(rel)+'.txt');target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);manifest[str(rel)]=hashlib.sha256(data).hexdigest()
  lines=data.split(b'\n') if data else []
  if data.endswith(b'\n'):lines.pop()
  matches=sum(b'ERROR' in line for line in lines);expected['files']+=1;expected['bytes']+=len(data);expected['lines']+=len(lines);expected['matching_lines']+=matches;expected['matching_files']+=matches>0
SRC=R/'tools/app-comparison';original=json.loads((W/'results.json').read_text())
for name,h in original['sources'].items():
 assert hashlib.sha256((SRC/name).read_bytes()).hexdigest()==h,('changed benchmark source',name)
commands={k:[str(W/f'{k}-app')] for k in ('dyn','gcc','clang','go')};commands['rust']=[str(W/'rust-target/release/rust-app')];commands['node']=[shutil.which('node'),str(SRC/'main.js')];commands['python']=[sys.executable,str(SRC/'main.py')]
os.sched_setaffinity(0,{4,5,6,7});samples={k:[] for k in commands};keys=list(commands)
for i in range(11):
 order=keys[i%7:]+keys[:i%7]
 if i//7%2:order.reverse()
 for k in order:
  p=subprocess.Popen([str(W/'peak'),'taskset','-c','2',*commands[k],'search',str(tree)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
  try:stdout,stderr=p.communicate(timeout=30)
  except BaseException:
   try:os.killpg(p.pid,signal.SIGKILL)
   except ProcessLookupError:pass
   p.wait(timeout=5);raise
  assert p.returncode==0,(k,p.returncode,stderr)
  assert json.loads(stdout)==expected,(k,stdout,expected)
  if i>=2:samples[k].append(json.loads(stderr.decode().splitlines()[-1]))
result={'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'input':'actual compiler src/std snapshot with original filenames suffixed .txt; no source edits','expected':expected,'manifest':manifest,'samples':samples,'medians':{k:{m:statistics.median(x[m] for x in v) for m in ('seconds','rss_mib')} for k,v in samples.items()}}
(W/'project-search.json').write_text(json.dumps(result,indent=2)+'\n');print(expected);print(result['medians'])
