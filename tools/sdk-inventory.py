#!/usr/bin/env python3
"""Regenerate mechanical source/direct-Dyn-fixture coverage inventory."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
importers={}
for source in sorted((ROOT/'tests').rglob('*.dyn')):
    for name in re.findall(r'\buse\s+"([^"]+)"',source.read_text()):
        importers.setdefault(name,set()).add(str(source.parent.relative_to(ROOT)))
rows=['source\tlines\tpublic_declarations\tdirect_test_importers']
for source in sorted((ROOT/'compiler').glob('*/**/*.dyn')):
    relative=source.relative_to(ROOT/'compiler')
    if relative.parts[0] not in ('std','vendor'): continue
    text=source.read_text();name=str(relative.parent)
    rows.append('\t'.join([str(source.relative_to(ROOT)),str(len(text.splitlines())),str(len(re.findall(r'^pub\s+',text,re.M))),','.join(sorted(importers.get(name,set())))]))
output = ROOT/'build/readiness/sdk-inventory.tsv'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text('\n'.join(rows)+'\n')
print(f'Inventoried {len(rows)-1} SDK source files')
