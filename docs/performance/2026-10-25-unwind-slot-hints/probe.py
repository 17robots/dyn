from pathlib import Path
import os,subprocess,json,time,statistics,hashlib,random
W=Path(__file__).resolve().parent; R=W.parents[1]
base=(R/'build/hot-inline-20261024/extended-source.dyn').read_text()
start=base.index('else if bytes.equal(mode,"allocate")')
body=base[start:base.index('}else {#panic("mode")}',start)+1]
variants={'typed':base,'raw':base.replace('mem.push_array(u64,&arena,8)','(#cast(*u64,mem.arena_push(&arena,64,8)))[..8]'),'uninit':base.replace('mem.push_array(u64,&arena,8)','(#cast(*u64,mem.arena_push_uninit(&arena,64,8)))[..8]'),'no-defer':base.replace('defer mem.arena_release(&arena)','').replace('_=io.println(io.stdout(),"{}",sum)','mem.arena_release(&arena)\n_=io.println(io.stdout(),"{}",sum)')}
alloc_body=body[len('else if bytes.equal(mode,"allocate") {'):-1]
helper='fn allocation_batch(arena:*mem.Arena,n,rounds:usize,seed:u32) u64 {\nsum:u64=0\n'+alloc_body.replace('&arena','arena')+'\nreturn sum\n}\n'
variants['outlined']=helper+base.replace(body,'else if bytes.equal(mode,"allocate") {sum=allocation_batch(&arena,n,rounds,seed)}')
env=dict(os.environ,DYN_SDK=str(R));env.pop('DYN_NO_SSA',None)
for name,source in variants.items():
 p=W/name;p.mkdir(exist_ok=True);(p/'main.dyn').write_text(source)
 cmd=[str(R/'build/dyn-release'),'build',str(p),'--release','--opt-level','3','--cpu','generic','--no-cache','--quiet','--output',str(W/name)+'-bin']
 c=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=120);assert c.returncode==0,c.stderr
 (W/(name+'.asm')).write_bytes(subprocess.check_output(['objdump','-d',str(W/name)+'-bin']))
print('built',flush=True)
seed=912345;n=8192;rounds=128
expected=0
for r in range(rounds):
 x=seed+r
 for _ in range(n*2):x=(x*1664525+1013904223)&0xffffffff;expected+=x
expected=str(expected&((1<<64)-1))+'\n'
results={k:[] for k in variants};order=[]
for i in range(17):
 names=list(variants); names=names[i%len(names):]+names[:i%len(names)]
 if i%2:names.reverse()
 for name in names:
  t=time.perf_counter_ns();p=subprocess.run([str(W/name)+'-bin','allocate',str(n),str(rounds),str(seed)],capture_output=True,text=True,timeout=30)
  elapsed=(time.perf_counter_ns()-t)/1e6
  assert p.returncode==0 and p.stdout==expected and not p.stderr,(name,p)
  if i>=2:results[name].append(elapsed)
 order.append(names)
print({k:statistics.median(v) for k,v in results.items()},flush=True)
(W/'results.json').write_text(json.dumps({'n':n,'rounds':rounds,'expected':expected,'warmups':2,'samples':15,'milliseconds':results,'order':order,'compiler_sha256':hashlib.sha256((R/'build/dyn-release').read_bytes()).hexdigest(),'note':'no-defer is diagnostic only; lacks panic cleanup; uninit omits zero contract'},indent=2))
