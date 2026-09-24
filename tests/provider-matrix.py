#!/usr/bin/env python3
"""Compile provider probes on their own OS/toolchain baseline; retain versions."""
import json, os, platform, subprocess, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
work=ROOT/'build/readiness'; work.mkdir(parents=True,exist_ok=True)
report={'host':platform.platform(),'compiler':subprocess.check_output([DYN,'version'],text=True).strip(),'providers':{},'tests':[]}
for name in ('openssl','sqlite3','libzstd'):
    report['providers'][name]=subprocess.check_output(['pkg-config','--modversion',name],text=True).strip()
try:
    for fixture in ('sdk-aead','sdk-zstd','sdk-sqlite','sdk-tls-native'):
        for release in (False,True):
            output=work/(fixture+('-release' if release else '-debug'))
            start=time.monotonic()
            subprocess.run([DYN,'build',str(ROOT/'tests'/fixture),'--no-cache','--quiet','--output',str(output)]+(['--release'] if release else []),check=True,timeout=120)
            subprocess.run([str(output)],check=True,timeout=60)
            report['tests'].append(dict(fixture=fixture,release=release,seconds=time.monotonic()-start,status='passed'))
finally:
    (work/'providers.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS provider contracts compiled and executed on this baseline')
