"""Frozen full-corpus proof and baseline-sensitive optimization controls."""
from pathlib import Path
import subprocess, hashlib, json, os, tempfile, shutil, runpy, resource

W = Path(__file__).resolve().parent
R = W.parents[1]
T = R/'build/json-twins-20261024'
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
want = json.loads((T/'corpus-verification.json').read_text())['normalized_sha256']
proof = {}
for mode in (0, 1):
    output = W/f'corpus-final-{mode}.jsonl'
    with output.open('wb') as f:
        subprocess.run([str(T/'driver'), str(W/'final-twin.so'), 'batch', str(mode), str(T/'corpus.bin')], stdout=f, check=True, timeout=120)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    assert digest == want, (mode, digest, want)
    proof[str(mode)] = digest
    output.unlink()
(W/'corpus-proof.json').write_text(json.dumps({'records': 60000, 'sha256_by_mode': proof}, indent=2)+'\n')
print('PASS 60000 exact documents and traces in both scanner modes', flush=True)

controls = {}
for name in ('ssa-compare-flags.py', 'ssa-byte-count.py'):
    p = subprocess.run(['python3', str(R/'tests'/name)], env=dict(os.environ, DYN=str(W/'dyn-before'), DYN_SDK=str(R)), capture_output=True, text=True, timeout=180)
    (W/(name+'.baseline.log')).write_text(p.stdout+p.stderr)
    assert p.returncode != 0, (name, 'baseline unexpectedly passes')
    controls[name] = {'baseline_status': p.returncode, 'log': name+'.baseline.log'}

with tempfile.TemporaryDirectory(prefix='dyn-old-spill-') as directory:
    work = Path(directory)
    shutil.copytree(R/'src', work/'src')
    shutil.copyfile(W/'ssa-before.inc', work/'src/backend/ssa.inc')
    harness = runpy.run_path(str(R/'tests/ssa-spill-compare.py'))['HARNESS']
    (work/'test.c').write_text(harness)
    subprocess.run(['cc', '-std=c11', '-D_GNU_SOURCE', '-D_POSIX_C_SOURCE=200809L', '-O1', '-ffunction-sections', '-fdata-sections', '-I'+str(work/'src'), str(work/'test.c'), '-Wl,--gc-sections', '-pthread', '-lm', '-o', str(work/'test')], check=True, timeout=120)
    p = subprocess.run([str(work/'test')], capture_output=True, text=True, timeout=20)
    (W/'ssa-spill-compare.py.baseline.log').write_text(p.stdout+p.stderr)
    assert p.returncode != 0, 'old spill emitter unexpectedly passes'
    controls['ssa-spill-compare.py'] = {'baseline_status': p.returncode, 'log': 'ssa-spill-compare.py.baseline.log'}
(W/'negative-controls.json').write_text(json.dumps(controls, indent=2)+'\n')
print('PASS baseline fails all three optimization controls', flush=True)
