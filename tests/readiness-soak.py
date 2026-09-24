#!/usr/bin/env python3
"""Bounded application/SDK/concurrency soak, with explicit duration and failure report."""
import json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
cycles=int(os.environ.get('DYN_SOAK_CYCLES','12'));assert 1<=cycles<=100000
work=ROOT/'build/readiness/soak';work.mkdir(parents=True,exist_ok=True)
report={'cycles_requested':cycles,'cycles_completed':0,'runs':0,'status':'running','fixtures':['release-concurrency','sdk-storage-contracts','sdk-archive','sdk-sqlite','sdk-process']}
start=time.monotonic()
try:
    binaries=[]
    for fixture in report['fixtures']:
        for release in (False,True):
            output=work/(fixture+('-release' if release else '-debug'))
            subprocess.run([DYN,'build',str(ROOT/'tests'/fixture),'--quiet','--no-cache','--output',str(output)]+(['--release'] if release else []),check=True,timeout=120)
            binaries.append(output)
    for cycle in range(cycles):
        for binary in binaries:
            result=subprocess.run([str(binary)],capture_output=True,text=True,cwd=ROOT,timeout=60)
            assert result.returncode==0,(binary,result.returncode,result.stdout,result.stderr)
            report['runs']+=1
        report['cycles_completed']=cycle+1
    subprocess.run(['python3','tests/readiness-workspace.py'],cwd=ROOT,env=dict(os.environ,DYN=DYN,DYN_WORKSPACE_CYCLES=str(cycles)),check=True,timeout=max(180,cycles*15))
    report['status']='passed'
except BaseException as error:
    report['status']='failed';report['error']=str(error);raise
finally:
    report['seconds']=time.monotonic()-start
    (ROOT/'build/readiness/soak.json').write_text(json.dumps(report,indent=2)+'\n')
print(f'PASS bounded soak: {report["runs"]} runtime executions and {cycles} workspace cycles')
