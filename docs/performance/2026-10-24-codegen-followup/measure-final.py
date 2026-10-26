"""Serial paired measurements; use frozen inputs and validate every output."""
from pathlib import Path
import subprocess, os, json, statistics, time, hashlib, random

W = Path(__file__).resolve().parent
R = W.parents[1]
T = R / 'build/json-twins-20261024'
I = R / 'build/json-language-isolation-20261024'
D = R / 'build/app-comparison-20261024'
os.sched_setaffinity(0, {2})
env = dict(os.environ, DYN_SDK=str(R))
thin = dict(env, LD_PRELOAD=str(T / 'common-thin.so'))
result = {}

def measure(label, variants, execute, retained=25):
    samples = {name: [] for name in variants}
    for rep in range(retained + 2):
        order = list(variants)
        order = order[rep % len(order):] + order[:rep % len(order)]
        if rep % 2:
            order.reverse()
        for name in order:
            ms = execute(variants[name])
            if rep >= 2:
                samples[name].append(ms)
    row = {'samples_ms': samples, 'median_ms': {n: statistics.median(s) for n, s in samples.items()}}
    result[label] = row
    (W / 'final-timing.json').write_text(json.dumps(result, indent=2) + '\n')
    print(label, row['median_ms'], flush=True)

def parser(lib):
    row = json.loads(subprocess.check_output([str(T/'driver'), str(lib), 'bench', '1', str(D/'events.jsonl'), '3'], env=thin, timeout=30))
    assert row['checksum'] == 1620000 and row['records'] == 180000, row
    return row['seconds'] * 1000 / 3

measure('parser', {'before': W/'before-twin.so', 'final': W/'final-twin.so', 'checked-c': T/'gcc-checked.so'}, parser)
proof = json.loads((I/'results.json').read_text())
for kernel in ('scan', 'integers', 'records', 'parse_lines'):
    def execute(lib):
        source = I/'records.bin' if kernel == 'records' else D/'events.jsonl'
        output = subprocess.check_output([str(I/'harness'), str(lib), kernel, str(source), str(proof['rounds'][kernel])], text=True, timeout=30)
        checksum, seconds = output.split()
        assert int(checksum) == proof['expected'][kernel], (kernel, output)
        return float(seconds) * 1000
    measure(kernel, {'before': W/'before-kernels.so', 'final': W/'final-kernels.so', 'checked-c': I/'c-checked.so', 'c': I/'c.so'}, execute)

def isolated(lib):
    output = subprocess.check_output([str(I/'harness'), str(lib), 'records', str(I/'records.bin'), str(proof['rounds']['records'])], text=True, timeout=30)
    checksum, seconds = output.split()
    assert int(checksum) == proof['expected']['records']
    return float(seconds) * 1000

measure('records-isolated', {'before': W/'before-records-isolated.so', 'final': W/'final-records-isolated.so'}, isolated, 41)
want = json.loads((D/'expected.json').read_text())
c_app = R/'build/faster-20261024/before/gcc-app'
for app in ('compact', 'mutable'):
    def report(executable):
        start = time.perf_counter()
        p = subprocess.run([str(executable), 'report', str(D/'events.jsonl')], env=env, capture_output=True, check=True, timeout=15)
        elapsed = time.perf_counter() - start
        assert json.loads(p.stdout) == want['report']
        return elapsed * 1000
    measure(app, {'before': W/('before-'+app), 'final': W/('final-'+app), 'c-yyjson': c_app}, report)

for label, folder, expected in [('large-search', D/'documents', want['search']), ('project-search', D/'project-snapshot', json.loads((D/'project-search.json').read_text())['expected'])]:
    def search(executable):
        start = time.perf_counter()
        p = subprocess.run([str(executable), 'search', str(folder)], env=env, capture_output=True, check=True, timeout=15)
        elapsed = time.perf_counter() - start
        assert json.loads(p.stdout) == expected
        return elapsed * 1000
    measure(label, {'before': W/'before-mutable', 'final': W/'final-mutable', 'c-yyjson': c_app}, search, 41)

rng = random.Random(20261024)
confidence = {}
for label, row in result.items():
    ss = row['samples_ms']
    ratios = [a/b for b, a in zip(ss['before'], ss['final'])]
    boot = sorted(statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(10000))
    confidence[label] = {'paired_median_final_before': statistics.median(ratios), 'bootstrap95': [boot[250], boot[9749]], 'samples': len(ratios)}
(W/'confidence.json').write_text(json.dumps(confidence, indent=2) + '\n')
files = [R/'build/dyn-release', W/'dyn-before', W/'dyn-final', T/'driver', T/'common-thin.so', I/'harness', c_app]
files += [W/(n+s) for n in ('before', 'final') for s in ('-twin.so', '-kernels.so', '-compact', '-mutable', '-records-isolated.so')]
(W/'binary-hashes.json').write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, indent=2) + '\n')
print('CONFIDENCE', json.dumps(confidence, indent=2), flush=True)
