#!/usr/bin/env python3
"""Execute the rule-family inventory; missing or misclassified fixtures fail."""
import json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
manifest=json.loads((ROOT/'docs/release/conformance.json').read_text())
rows=[]
for rule in manifest['rules']:
    for check in rule['checks']: assert (ROOT/check).is_file(),check
    for outcome in ('positive','negative'):
        for fixture in rule[outcome]:
            assert (ROOT/fixture).is_dir() and list((ROOT/fixture).glob('*.dyn')),fixture
            r=subprocess.run([DYN,'check',str(ROOT/fixture),'--quiet','--no-cache'],capture_output=True,text=True,timeout=60)
            assert r.returncode in (0,1) and (r.returncode==0)==(outcome=='positive'),(rule['id'],fixture,r.returncode,r.stderr)
            rows.append(dict(rule=rule['id'],fixture=fixture,expected=outcome,status='passed'))
(ROOT/'build/readiness').mkdir(parents=True,exist_ok=True)
(ROOT/'build/readiness/conformance.json').write_text(json.dumps(rows,indent=2)+'\n')
print(f'PASS {len(rows)} specification-family positive/negative fixtures')
