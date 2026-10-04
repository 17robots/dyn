#!/usr/bin/env python3
"""Cold/warm/novel-edit/runtime matrix; all outputs and edits are isolated.

Cold means an empty Dyn cache, not an empty OS page cache. Uses the standard
library workload in tests/performance and changes an executed iteration bound.
No timing thresholds: retain raw samples for comparisons on the same machine.
"""
import argparse, hashlib, json, os, platform, statistics, subprocess, time
from pathlib import Path
from benchmark import measure
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--dyn',type=Path,default=ROOT/'build'/('dyn-release.exe' if os.name=='nt' else 'dyn-release'))
p.add_argument('--samples',type=int,default=5)
p.add_argument('--output',type=Path,default=ROOT/'build'/('performance-'+str(time.time_ns())))
a=p.parse_args()
if a.samples<1: p.error('--samples must be positive')
if a.output.exists(): p.error('use a new output directory to keep cold/edited samples honest')
a.output.mkdir(parents=True); work=a.output.resolve(); compiler=a.dyn.resolve()
source=(ROOT/'tests/performance/main.dyn').read_text()
compiler_hash=hashlib.sha256(compiler.read_bytes()).hexdigest()
source_hash=hashlib.sha256(source.encode()).hexdigest()
variants={'portable':[], 'native':['--cpu','native'], 'o3':['--opt-level','3'], 'no-lto':['--no-lto']}
rows=[]
for name in variants:
    (work/name/'src').mkdir(parents=True)
for trial in range(a.samples):
    order=list(variants) if trial%2==0 else list(reversed(variants))
    for name in order:
        folder=work/name; src=folder/'src/main.dyn'; output=folder/('program.exe' if os.name=='nt' else 'program')
        src.write_text(source)
        env=dict(os.environ,DYN_CACHE_DIR=str(folder/f'cache-{trial}'))
        output.unlink(missing_ok=True)
        command=[str(compiler),'build',str(src.parent),'--release','--timings','--output',str(output),*variants[name]]
        for case in ('cold','warm','edited'):
            if case=='edited':
                src.write_text(source.replace('0..2000',f'0..{2001+trial}'))
            row=measure(command,env,120)
            rows.append(dict(variant=name,trial=trial,case=case,artifact_bytes=output.stat().st_size,**row))
        # Runtime uses identical source across variants/trials.
        src.write_text(source); measure(command,env,120)
        rows.append(dict(variant=name,trial=trial,case='runtime',artifact_bytes=output.stat().st_size,
                         **measure([str(output)],env,120)))
        (work/'results.json').write_text(json.dumps(dict(platform=platform.platform(),compiler=str(compiler),
            compiler_sha256=compiler_hash,source_sha256=source_hash,
            compiler_version=subprocess.check_output([str(compiler),'version'],text=True).strip(),
            rss_definition='wait4 maximum, not concurrent aggregate',samples=rows),indent=2)+'\n')
        print(name,trial,flush=True)
assert len({r['stdout_sha256'] for r in rows if r['case']=='runtime'})==1, 'runtime checksum mismatch'
summary={name:{case:statistics.median(r['seconds'] for r in rows if r['variant']==name and r['case']==case)
              for case in ('cold','warm','edited','runtime')} for name in variants}
(work/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
