#!/usr/bin/env python3
"""Wide-function scaling, separating qualified rewriting from direct calls."""
import argparse, hashlib, json, os, platform, re, statistics, subprocess, tempfile, time
from pathlib import Path
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path)
parser.add_argument('--verify', action='store_true')
parser.add_argument('--repeats', type=int, default=3)
args = parser.parse_args()
if args.repeats < 1: parser.error('--repeats must be positive')
dyn = str(Path(os.environ.get('DYN', 'build/dyn-release')).resolve())
rows = []
with tempfile.TemporaryDirectory(prefix='dyn-wide-') as directory:
    root = Path(directory)
    for kind in ('qualified', 'direct', 'locals'):
        for count in (1024, 4096):
            project = root/f'{kind}-{count}'; project.mkdir()
            if kind == 'qualified':
                (project/'lib').mkdir()
                (project/'lib/module.dyn').write_text('pub fn value() i32 { return 1 }\n')
                prefix, call = 'use "./lib" m\n', 'm.value()'
            else:
                prefix, call = 'fn value() i32 { return 1 }\n', 'value()'
            body = ''.join(f'local{i} := {i}\n_ = local{i}\n' for i in range(count)) if kind == 'locals' else ''.join(f'_ = {call}\n' for _ in range(count))
            (project/'main.dyn').write_text(prefix+'fn main() {\n'+body+'}\n')
            samples = []
            for _ in range(args.repeats):
                start = time.monotonic()
                run = subprocess.run([dyn,'check',str(project),'--no-cache','--quiet','--timings','--jobs','1'],capture_output=True,text=True,check=True,timeout=120)
                phases = {key:float(value) for key,value in re.findall(r'^timing (.+?) ([\d.]+) ms$',run.stderr,re.M)}
                samples.append({'wall_ms':(time.monotonic()-start)*1000,'phases_ms':phases})
            row = {'kind':kind,'count':count,'samples':samples,'median_ms':statistics.median(s['wall_ms'] for s in samples),
                   'median_sema_ms':statistics.median(s['phases_ms']['detail sema'] for s in samples)}
            rows.append(row)
            print(f'{kind} {count}: {row["median_ms"]:.2f} ms',flush=True)
report = {'compiler':dyn,'compiler_sha256':hashlib.sha256(Path(dyn).read_bytes()).hexdigest(),'host':platform.platform(),'repeats':args.repeats,'rows':rows}
if args.output:
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
if args.verify:
    for small,large in zip(rows[::2],rows[1::2]):
        # Four times the work must stay comfortably below quadratic growth.
        assert large['median_ms'] < small['median_ms']*8+20, (small['kind'],small['median_ms'],large['median_ms'])
        if small['kind'] == 'locals':
            assert large['median_sema_ms'] < small['median_sema_ms']*8+2, (small,large)
print('PASS wide-function scaling' if args.verify else 'Recorded wide-function baseline')
