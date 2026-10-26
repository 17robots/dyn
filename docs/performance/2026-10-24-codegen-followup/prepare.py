from pathlib import Path
import subprocess,os,json,hashlib
W=Path(__file__).resolve().parent;R=W.parents[1];T=R/'build/json-twins-20261024';I=R/'build/json-language-isolation-20261024';env=dict(os.environ,DYN_SDK=str(R));commands=[];names=os.environ.get('VARIANTS','before,branches,spills,loops,combined').split(',')
for name in names:
 compiler=W/('dyn-'+name)
 for source,suffix,flags in [(T/'dyn','twin.so',['--shared','--link',str(T/'common.so')]),(I/'dyn','kernels.so',['--shared']),(R/'build/compact-json-20261024/app-read','compact',[]),(R/'tools/app-comparison','mutable',[])]:
  cmd=[str(compiler),'build',str(source),'--release','--opt-level','3','--cpu','generic','--no-cache','--quiet','--opt-remarks',*flags,'--output',str(W/(name+'-'+suffix))]
  p=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=120);assert p.returncode==0,(name,suffix,p.stderr)
  (W/(name+'-'+suffix+'.remarks')).write_text(p.stderr);commands.append(cmd)
 print('BUILT programs',name,flush=True)
(W/'program-builds.json').write_text(json.dumps(commands,indent=2))
# Frozen cases include full normalized DOM, failures, traces and helper counts.
comparisons=0
for mode in (0,1):
 expected=subprocess.check_output([str(T/'driver'),str(T/'gcc-checked.so'),'batch',str(mode),str(T/'cases.bin')],timeout=120)
 for name in names:
  actual=subprocess.check_output([str(T/'driver'),str(W/(name+'-twin.so')),'batch',str(mode),str(T/'cases.bin')],timeout=120)
  assert actual==expected,(name,mode);comparisons+=1828
(W/'verification.json').write_text(json.dumps({'frozen_case_comparisons':comparisons,'modes':[0,1],'variants':names},indent=2))
print('PASS',comparisons,'exact frozen parser comparisons',flush=True)
(W/'program-hashes.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for n in names for p in [W/('dyn-'+n),*(W/(n+'-'+x) for x in ('twin.so','kernels.so','compact','mutable'))]},indent=2))
