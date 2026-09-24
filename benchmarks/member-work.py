#!/usr/bin/env python3
"""Repeated type/member access and debug-local scaling; fresh uncached commands."""
import argparse, hashlib, json, os, re, statistics, subprocess, tempfile
from pathlib import Path
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--repeats', type=int, default=3)
p.add_argument('--verify', action='store_true')
a = p.parse_args()
if a.repeats < 1: p.error('--repeats must be positive')
dyn = str(Path(os.environ.get('DYN', 'build/dyn-release')).resolve())
rows = []
with tempfile.TemporaryDirectory(prefix='dyn-member-work-') as directory:
    root = Path(directory)
    for kind in ('types', 'fields', 'debug_locals'):
        for size in (256, 2048):
            if kind == 'types':
                text = ''.join(f'struct T{i} {{ value: i32 }}\n' for i in range(size))
                text += ''.join(f'fn read{i}(x: T{i}) i32 {{ return x.value }}\n' for i in range(size))
            elif kind == 'fields':
                text = 'struct Wide { '+', '.join(f'f{i}: i32' for i in range(size))+' }\n'
                text += 'fn read(x: Wide) { '+' '.join(f'_ = x.f{i}' for i in range(size) for repeat in range(4))+' }\n'
            else:
                text = 'fn work() { '+' '.join(f'x{i} := {i} _ = x{i}' for i in range(size))+' }\n'
            text += 'fn main() {}\n'
            (root/'main.dyn').write_text(text)
            samples = []
            for _ in range(a.repeats):
                command = [dyn, 'build' if kind == 'debug_locals' else 'check', str(root), '--quiet', '--no-cache', '--jobs', '1', '--timings']
                if kind == 'debug_locals': command += ['--no-link', '--output', str(root/'out.o')]
                result = json.loads(subprocess.check_output(['python3', 'benchmarks/compiler-phases.py', '--measure', *command], text=True))
                assert result['returncode'] == 0, result['stderr']
                phases = {}
                for detail, name, ms in re.findall(r'^timing (detail )?(\w+) ([\d.]+) ms$',result['stderr'],re.M):
                    key = ('detail_' if detail else '')+name
                    phases[key] = phases.get(key,0)+float(ms)
                samples.append(dict(wall_ms=result['wall_ms'], phases_ms=phases))
            rows.append(dict(kind=kind,size=size,samples=samples,median_ms=statistics.median(x['wall_ms'] for x in samples),median_phases_ms={k:statistics.median(x['phases_ms'][k] for x in samples) for k in samples[0]['phases_ms']}))
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(dict(compiler_sha256=hashlib.sha256(Path(dyn).read_bytes()).hexdigest(),workloads=rows),indent=2)+'\n')

if a.verify:
    for kind, phase, slack in [('fields', 'detail_sema', 0.5), ('debug_locals', 'detail_llvm', 2.0)]:
        small, large = [r for r in rows if r['kind'] == kind]
        before = small['median_phases_ms'][phase]
        after = large['median_phases_ms'][phase]
        assert after <= 16 * before + slack, (kind, phase, before, after)
    print('PASS repeated-member and debug-local scaling')
