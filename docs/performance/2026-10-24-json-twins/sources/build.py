from pathlib import Path
import subprocess,os,shutil,json,hashlib
W=Path(__file__).resolve().parent;R=Path(os.environ.get('DYN_SOURCE_ROOT',str(W.parents[1]))).resolve()
commands=[]
def run(args,**kwargs):
 commands.append(list(map(str,args)));p=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=180,**kwargs)
 assert p.returncode==0,(args,p.stdout,p.stderr)
 if p.stdout:print(p.stdout,end='')
 if p.stderr:(W/('build-'+str(len(commands))+'.log')).write_text(p.stderr)
flags=['-std=c11','-O3','-march=x86-64','-fPIC']
run(['gcc',*flags,'-fno-tree-vectorize','-shared',W/'common.c','-o',W/'common.so'])
run(['gcc',*flags,'-fno-tree-vectorize','-DLAB_TRACE=0','-shared',W/'common.c','-o',W/'common-thin.so'])
for name,cc,opts in [('gcc','gcc',[]),('gcc-checked','gcc',['-DCHECKED=1']),('gcc-scalar','gcc',['-fno-tree-vectorize']),('gcc-checked-scalar','gcc',['-DCHECKED=1','-fno-tree-vectorize']),('clang','clang',[]),('clang-checked','clang',['-DCHECKED=1']),('gcc-noinline','gcc',['-fno-inline']),('gcc-checked-noalias','gcc',['-DCHECKED=1','-fno-strict-aliasing']),('gcc-checked-noclone','gcc',['-DCHECKED=1','-fno-ipa-cp']),('gcc-checked-frame','gcc',['-DCHECKED=1','-fno-omit-frame-pointer']),('gcc-checked-conservative','gcc',['-DCHECKED=1','-fno-strict-aliasing','-fno-ipa-cp','-fno-omit-frame-pointer','-fno-delete-null-pointer-checks'])]:
 run([cc,*flags,*opts,'-shared',W/('twin-conservative.c' if name=='gcc-checked-conservative' else 'twin.c'),W/'common.so','-Wl,-rpath,$ORIGIN','-o',W/(name+'.so')])
for name,mode in [('dyn',False),('dyn-tree',True)]:
 run([R/'build/dyn-release','build',W/'dyn','--release','--opt-level','3','--cpu','generic','--shared','--no-cache','--quiet','--link',W/'common.so','--output',W/(name+'.so')],env=dict(os.environ,DYN_SDK=str(R),DYN_NO_SSA='1' if mode else '0'))
run(['gcc','-std=c11','-O2',W/'driver.c',W/'common.so','-Wl,-rpath,$ORIGIN','-ldl','-o',W/'driver'])
(W/'build-commands.json').write_text(json.dumps(commands,indent=2)+'\n')
(W/'binary-hashes.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in W.glob('*.so')},indent=2)+'\n');print('Built all matched twins; no timings run')
