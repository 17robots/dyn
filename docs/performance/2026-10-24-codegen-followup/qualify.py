"""Run the registered suite, preserving gate order/timeouts and individual logs."""
import hashlib,json,os,runpy,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[2];out=Path(__file__).resolve().parent/'qualification';out.mkdir(exist_ok=True)
os.chdir(root)
original=subprocess.run;results=[]
def snapshot():
 return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('src','std','runtime','tests','tools') for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in str(p) and p.suffix not in ('.pyc',)}
(out/'hashes-before.json').write_text(json.dumps(snapshot(),indent=2)+'\n')
def recorded(command,*args,**kwargs):
 index=len(results)+1;name=Path(str(command[1] if len(command)>1 and str(command[0])==sys.executable else command[0])).name
 path=out/f'{index:03}-{name}.log';start=time.monotonic();code=None;failure=None
 with path.open('w') as log:
  try:
   value=original(command,*args,**dict(kwargs,stdout=log,stderr=subprocess.STDOUT));code=value.returncode
  except subprocess.CalledProcessError as e:code=e.returncode;failure=e
  except subprocess.TimeoutExpired as e:code=124;failure=e
 text=path.read_text(errors='replace');skip=[line for line in text.splitlines() if line.startswith('SKIP') or line.startswith('skip:')]
 row={'index':index,'name':name,'command':list(map(str,command)),'timeout':kwargs.get('timeout'),'code':code,'seconds':round(time.monotonic()-start,3),'skip_lines':skip,'log':str(path)};results.append(row)
 (out/'results.json').write_text(json.dumps(results,indent=2)+'\n');print(('PASS' if code==0 else 'FAIL'),index,name,row['seconds'],f'skips={len(skip)}',flush=True)
 if failure:raise failure
 return value
subprocess.run=recorded
try:
 runpy.run_path(str(root/'tests/run.py'),run_name='__main__')
finally:
 (out/'hashes-after.json').write_text(json.dumps(snapshot(),indent=2)+'\n')
 (out/'summary.json').write_text(json.dumps({'gates':len(results),'passed':sum(r['code']==0 for r in results),'failed':sum(r['code']!=0 for r in results),'skip_lines':sum(len(r['skip_lines']) for r in results)},indent=2)+'\n')
