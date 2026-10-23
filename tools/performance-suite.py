#!/usr/bin/env python3
"""Cold/warm/novel-edit/runtime matrix; all outputs and edits are isolated.

Cold means an empty Dyn cache, not an empty OS page cache. Uses the standard
library workload in tests/performance and changes an executed iteration bound.
No timing thresholds: retain raw samples for comparisons on the same machine.
"""
import argparse, hashlib, json, os, platform, re, statistics, subprocess, time
from pathlib import Path
from benchmark import measure
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--dyn',type=Path,default=ROOT/'build'/('dyn-release.exe' if os.name=='nt' else 'dyn-release'))
p.add_argument('--samples',type=int,default=5)
p.add_argument('--profile-code',action='store_true',help='separate monolithic optimized code size/phase measurements')
p.add_argument('--output',type=Path,default=ROOT/'build'/('performance-'+str(time.time_ns())))
a=p.parse_args()
if a.samples<1: p.error('--samples must be positive')
if a.output.exists(): p.error('use a new output directory to keep cold/edited samples honest')
a.output.mkdir(parents=True); work=a.output.resolve(); compiler=a.dyn.resolve()
source=(ROOT/'tests/performance/main.dyn').read_text()
compiler_hash=hashlib.sha256(compiler.read_bytes()).hexdigest()
source_hash=hashlib.sha256(source.encode()).hexdigest()
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def std_manifest(): return {str(p.relative_to(ROOT)):digest(p) for p in sorted((ROOT/'std').rglob('*.dyn'))}
def runtime_manifest():
    folders=[compiler.parent,compiler.parent/'../lib/dyn']
    names={p.name for folder in folders for p in folder.glob('dynrt*.o')}
    paths=[next(folder/name for folder in folders if os.access(folder/name,os.R_OK)) for name in sorted(names)]
    return {str(p.resolve()):digest(p) for p in paths}
stdlib=std_manifest(); runtimes=runtime_manifest()
version=subprocess.check_output([str(compiler),'version'],text=True).strip()
def checked_measure(command,env):
    row=measure(command,env,120)
    row.update(command=command,environment_overrides={key:env[key] for key in ('DYN_SDK','DYN_CACHE_DIR')})
    row['phase_samples']=[dict(phase=phase,seconds=float(ms)/1000,peak_mib=int(peak) if peak else None)
        for phase,ms,peak in re.findall(r'^timing detail (.+?) ([\d.]+) ms(?:, peak (\d+) MiB)?$',row['stderr'],re.M)]
    return row
variants={'portable':[], 'native':['--cpu','native'], 'o3':['--opt-level','3']}
rows=[]
for name in variants:
    (work/name/'src').mkdir(parents=True)
for trial in range(a.samples):
    order=list(variants) if trial%2==0 else list(reversed(variants))
    for name in order:
        folder=work/name; src=folder/'src/main.dyn'; output=folder/('program.exe' if os.name=='nt' else 'program')
        src.write_text(source)
        env=dict(os.environ,DYN_SDK=str(ROOT),DYN_CACHE_DIR=str(folder/f'cache-{trial}'))
        output.unlink(missing_ok=True)
        command=[str(compiler),'build',str(src.parent),'--release','--timings','--output',str(output),*variants[name]]
        for case in ('cold','warm','edited'):
            if case=='edited':
                src.write_text(source.replace('0..2000',f'0..{2001+trial}'))
            row=checked_measure(command,env)
            rows.append(dict(variant=name,trial=trial,case=case,artifact_bytes=output.stat().st_size,**row))
        # Runtime uses identical source across variants/trials.
        src.write_text(source); checked_measure(command,env)
        rows.append(dict(variant=name,trial=trial,case='runtime',artifact_bytes=output.stat().st_size,
                         **checked_measure([str(output)],env)))
        (work/'results.json').write_text(json.dumps(dict(platform=platform.platform(),compiler=str(compiler),
            compiler_sha256=compiler_hash,source_sha256=source_hash,
            compiler_version=version,std_sha256=stdlib,runtime_sha256=runtimes,
            tool_sha256={str(path.relative_to(ROOT)):digest(path) for path in (Path(__file__),ROOT/'tools/benchmark.py')},
            rss_definition='wait4 maximum, not concurrent aggregate',samples=rows),indent=2)+'\n')
        print(name,trial,flush=True)
assert len({(r['stdout_sha256'],r['stderr']) for r in rows if r['case']=='runtime'})==1, 'runtime output mismatch'
assert digest(compiler)==compiler_hash and std_manifest()==stdlib and runtime_manifest()==runtimes, 'compiler/SDK changed during measurements'
if a.profile_code:
    profiles=[]
    for name,flags in variants.items():
        folder=work/name; output=folder/'profile'; env=dict(os.environ,DYN_SDK=str(ROOT),DYN_CACHE_DIR=str(folder/'profile-cache'))
        command=[str(compiler),'build',str(folder/'src'),'--release','--emit-asm','--no-link','--no-cache','--timings','--jobs','1','--output',str(output),*flags]
        row=checked_measure(command,env); assembly=Path(str(output)+'.s'); text=assembly.read_text()
        profiles.append(dict(variant=name,scope='Separate monolithic optimized assembly emission; not the modular timed build path.',
            object_bytes=Path(str(output)+'.o').stat().st_size,assembly_sha256=digest(assembly),function_definitions=len(re.findall(r'^"[^"]+":$',text,re.M)),**row))
    (work/'code-profiles.json').write_text(json.dumps(profiles,indent=2)+'\n')
assert digest(compiler)==compiler_hash and std_manifest()==stdlib and runtime_manifest()==runtimes, 'compiler/SDK changed during profiling' 
summary={name:{case:statistics.median(r['seconds'] for r in rows if r['variant']==name and r['case']==case)
              for case in ('cold','warm','edited','runtime')} for name in variants}
(work/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
