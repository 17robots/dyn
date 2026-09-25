#!/usr/bin/env python3
"""Scaling and regression checks for imports, wide structs, rewrites and edits."""
import argparse, hashlib, json, os, platform, re, statistics, subprocess, sys, tempfile, time
from pathlib import Path
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--baseline', type=Path)
parser.add_argument('--verify', action='store_true', help='Reject superlinear scaling on this host')
parser.add_argument('--repeats', type=int, default=5)
args = parser.parse_args()
if args.repeats < 1: parser.error('--repeats must be positive')
dyn = str(Path(os.environ.get('DYN', 'build/dyn-release')).resolve())
probe = str(Path(os.environ.get('DYN_PERF', 'build/dyn-perf')).resolve())
machine = {'system':platform.system(), 'machine':platform.machine(), 'node':platform.node(),
           'cpu_model':next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), platform.processor())}
report = {'machine':machine, 'compiler_sha256':hashlib.sha256(Path(dyn).read_bytes()).hexdigest(),
          'host':platform.platform(), 'repeats':args.repeats, 'workloads':[], 'allocation_scope':'compiler and generated parser only; requested bytes include realloc requests',
          'rss_scope':'fresh helper maximum RSS; includes shared libraries'}
with tempfile.TemporaryDirectory(prefix='dyn-scaling-') as directory:
    root = Path(directory)
    for kind in ('imports', 'struct_fields', 'rewrites'):
        for size in {'struct_fields':(32,128,512), 'imports':(8,32,128), 'rewrites':(128,1024,4096)}[kind]:
            project = root/f'{kind}-{size}'; project.mkdir()
            if kind == 'imports':
                imports, uses = [], []
                for i in range(size):
                    module = project/f'lib{i}'; module.mkdir()
                    (module/'module.dyn').write_text('pub fn value() i32 { return 1 }\n')
                    imports.append(f'use "./lib{i}" m{i}')
                    uses.append(f'_ = m{i}.value()')
                text = '\n'.join(imports)+'\nfn main() { '+' '.join(uses)+' }\n'
            elif kind == 'struct_fields':
                text = 'struct Wide {\n'+',\n'.join(f'f{i}: i32' for i in range(size))+'\n}\n'
                text += 'fn read(value: Wide) i32 { return value.f'+str(size-1)+' }\nfn main() {}\n'
            else:
                module = project/'lib'; module.mkdir()
                (module/'module.dyn').write_text('pub fn value() i32 { return 1 }\n')
                text = 'use "./lib" m\nfn main() { '+' '.join('_ = m.value()' for _ in range(size))+' }\n'
            (project/'main.dyn').write_text(text)
            samples = []
            command = ['check',str(project),'--quiet','--no-cache','--jobs','1']
            for _ in range(args.repeats):
                row = json.loads(subprocess.check_output([sys.executable,'benchmarks/compiler-phases.py','--measure',dyn,*command],text=True))
                assert row['returncode'] == 0, row
                samples.append({key:row[key] for key in ('wall_ms','peak_rss_kib')})
            allocations = subprocess.run([probe,*command],env=dict(os.environ,DYN_ALLOCATION_STATS='1'),capture_output=True,text=True,check=True)
            counts = re.search(r'compiler-allocations calls=(\d+) requested-bytes=(\d+)', allocations.stderr)
            assert counts, allocations.stderr
            report['workloads'].append({'kind':kind,'size':size,'samples':samples,
                'median_ms':statistics.median(x['wall_ms'] for x in samples),
                'max_ms':max(x['wall_ms'] for x in samples),
                'median_rss_kib':statistics.median(x['peak_rss_kib'] for x in samples),
                'allocation_calls':int(counts[1]),'allocation_requested_bytes':int(counts[2])})
    # Existing serialized editor workload records every sample, not just a median.
    editor = json.loads(subprocess.check_output([sys.executable,'benchmarks/frontend-work.py'],env=dict(os.environ,DYN=dyn),text=True))
    edits = sorted(x*1000 for x in editor['edit_diagnostic_seconds'])
    report['editor'] = {'samples_ms':edits,'median_ms':statistics.median(edits),
                        'p95_ms':edits[(len(edits)*95+99)//100-1],'max_ms':max(edits)}
    bursts = sorted(x*1000 for x in editor['burst_seconds'])
    report['editor_bursts'] = {'samples_ms':bursts, 'median_ms':statistics.median(bursts),
                              'p95_ms':bursts[(len(bursts)*95+99)//100-1], 'max_ms':max(bursts)}
    # Burst protocol/order assertions are deterministic even on a busy host.
    subprocess.run([sys.executable,'tests/lsp-scheduling.py'],env=dict(os.environ,DYN=dyn),check=True)
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,indent=2)+'\n')
if args.verify:
    for kind in ('imports', 'struct_fields', 'rewrites'):
        rows = [r for r in report['workloads'] if r['kind'] == kind]
        for small, large in zip(rows, rows[1:]):
            ratio = large['size'] / small['size']
            for metric, slack in [('median_ms', 20), ('allocation_calls', 1000), ('allocation_requested_bytes', 1024*1024)]:
                assert large[metric] <= small[metric]*ratio*2 + slack, (kind, metric, small[metric], large[metric])
if args.baseline:
    baseline = json.loads(args.baseline.read_text())
    if baseline.get('machine') != report['machine']:
        raise SystemExit('Performance baseline belongs to a different or unidentified machine; collect a new same-runner baseline')
    failures = []
    for old,new in zip(baseline['workloads'],report['workloads'],strict=True):
        assert (old['kind'],old['size']) == (new['kind'],new['size'])
        for metric,factor,slack in [('median_ms',1.35,2),('median_rss_kib',1.25,4096),('allocation_calls',1.15,100),('allocation_requested_bytes',1.25,4096)]:
            if new[metric] > old[metric]*factor+slack: failures.append((new['kind'],new['size'],metric,old[metric],new[metric]))
    for key in ('editor', 'editor_bursts'):
        if report[key]['p95_ms'] > baseline[key]['p95_ms']*1.5+2:
            failures.append((key,'p95_ms',baseline[key]['p95_ms'],report[key]['p95_ms']))
    if failures: raise SystemExit('Performance regressions: '+repr(failures))
print('PASS compiler scaling, allocation/RSS samples and editor latency:',args.output)
