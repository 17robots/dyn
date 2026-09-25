#!/usr/bin/env python3
"""Validate and package the standalone compiler; native execution runs separately."""
import hashlib,json,os,shutil,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BUILD=Path(os.environ.get('BUILD',ROOT/'build')).resolve()
OUT=BUILD/'release-check'
OUT.mkdir(parents=True,exist_ok=True)
shutil.rmtree(OUT/'artifacts',ignore_errors=True)
report=dict(status='running',scope='Standalone compiler regressions and relocated SDK',stages=[])
(OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
try:
    for name,command in [('compiler',['just','test']),('package',['just','package'])]:
        start=time.monotonic()
        with (OUT/(name+'.log')).open('w') as log:
            result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
        report['stages'].append(dict(name=name,status='passed' if result.returncode==0 else 'failed',seconds=time.monotonic()-start))
        if result.returncode:raise RuntimeError(name+' failed; see '+str(OUT/(name+'.log')))
    package=json.loads((BUILD/'dist/package-validation.json').read_text())
    destination=OUT/'artifacts';destination.mkdir()
    archive=destination/package['archive'];shutil.copy2(BUILD/'dist'/archive.name,archive)
    report['artifacts']={'build/release-check/artifacts/'+archive.name:hashlib.sha256(archive.read_bytes()).hexdigest()}
    report['compiler_sha256']=hashlib.sha256((BUILD/'dyn-release').read_bytes()).hexdigest()
    report['grammar']=json.loads((ROOT/'grammar.lock.json').read_text())
    report['status']='passed'
except BaseException as error:
    report.update(status='failed',error=str(error));raise
finally:
    (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS standalone compiler release checks')
