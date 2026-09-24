#!/usr/bin/env python3
"""Record conservative public SDK references; never equate references with behavior coverage."""
import argparse,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');a=p.parse_args()
uses={}
for path in sorted((ROOT/'tests').rglob('*.dyn')):
    text=path.read_text()
    for match in re.finditer(r'^use\s+"((?:std|vendor)/[^"\n]+)"(?:[ \t]+([A-Za-z_]\w*))?',text,re.M):
        package,alias=match.groups();alias=alias or package.rsplit('/',1)[-1]
        for name in re.findall(r'\b'+re.escape(alias)+r'\s*\.\s*([A-Za-z_]\w*)',text):
            uses.setdefault((package,name),set()).add(str(path.relative_to(ROOT)))
rows=[]
for collection in ('std','vendor'):
    for path in sorted((ROOT/'compiler'/collection).rglob('*.dyn')):
        package=str(path.parent.relative_to(ROOT/'compiler'))
        for kind,name in re.findall(r'^pub\s+(?:(?:extern|distinct|packed)\s+)?(fn|struct|enum|type|const)\s+(\w+)',path.read_text(),re.M):
            rows.append(dict(package=package,source=str(path.relative_to(ROOT)),kind=kind,name=name,direct_test_references=sorted(uses.get((package,name),set()))))
report={'scope':'Mechanical direct qualified references in checked-in Dyn fixtures only; excludes generated Python test sources and transitive calls; does not resolve comments, bindings or behavioral assertions and can include textual false positives. Not a coverage certificate.', 'public_declarations':len(rows),'declarations_with_direct_references':sum(bool(r['direct_test_references']) for r in rows),'declarations':rows}
output=ROOT/'docs/release/sdk-api-references.json';data=json.dumps(report,indent=2)+'\n'
if a.check: assert output.exists() and output.read_text()==data,'SDK API reference inventory changed; run tools/readiness-inventory.py and review the delta'
else: output.write_text(data)
print(f'SDK reference inventory: {len(rows)} declarations, {report["declarations_with_direct_references"]} directly referenced; behavioral review remains separate')
