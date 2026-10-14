#!/usr/bin/env python3
"""Compare compiler acceptance and exact diagnostics after deterministic mutations.

This gate does not prove parser equivalence. It exercises compact-first fallback
and semantic entry with malformed as well as valid byte sequences. Both compilers
see the same path, SDK, cache policy and source bytes.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sdk_manifest():
    return {str(path.relative_to(ROOT)): digest(path.read_bytes())
            for path in sorted((ROOT/'std').rglob('*.dyn'))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--reference', type=Path, default=ROOT/'build/dyn-legacy')
    parser.add_argument('--samples', type=int, default=1000)
    parser.add_argument('--seed', type=int, default=20261015)
    parser.add_argument('--corpus', type=Path, action='append', default=[],
                        help='also mutate .dyn files under this directory; repeatable')
    parser.add_argument('--output', type=Path, required=True, help='new evidence directory')
    args = parser.parse_args()
    if args.samples < 1:
        parser.error('--samples must be positive')
    if args.output.exists():
        parser.error('--output must be a new directory')
    args.output.mkdir(parents=True)
    output = args.output.resolve()
    compilers = [args.reference.resolve(), args.compiler.resolve()]
    compiler_hashes = [digest(p.read_bytes()) for p in compilers]
    sdk_hashes = sdk_manifest()
    spec = importlib.util.spec_from_file_location('extract_tests', HERE/'extract-tests.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bases = [('calibration-valid', b'fn main() {}'),
             ('calibration-invalid', b'fn main() { _ = }')]
    bases += [(f'source-cases.json:{i}', case['source'].encode()) for i, case in
              enumerate(json.loads((HERE/'source-cases.json').read_text()))]
    bases += [(f"first-regressions.json:{case['name']}", case['source'].encode())
              for case in json.loads((HERE/'first-regressions.json').read_text())]
    bases += [(f"{case['path']}:{case['line']}", case['source'].encode())
              for case in module.extract_test_sources(ROOT)]
    for folder in args.corpus:
        bases += [(str(path.resolve()), path.read_bytes()) for path in sorted(folder.rglob('*.dyn'))]
    rng = random.Random(args.seed)
    # Include invalid UTF-8, NULs, non-ASCII whitespace and lexical delimiters.
    insertions = [b'\x00', b'\xff', b'\xc0\xaf', b'\xe2\x80\xa8', b'\r\n', b'/*',
                  b'*/', b'//', b'"', b"'", b'\\', b'(', b')', b'[', b']', b'{', b'}',
                  b':', b'=', b'..=', b'pub ', b'const ', b'fn ', b'#target(', b'$T']
    cases = [(origin, 'original', data) for origin, data in bases]
    for _ in range(args.samples):
        origin, data = rng.choice(bases)
        at = rng.randrange(len(data)+1)
        operation = rng.choice(('insert', 'delete', 'replace', 'truncate', 'duplicate'))
        count = rng.randrange(1, 9)
        if operation == 'insert':
            mutated = data[:at]+rng.choice(insertions)+data[at:]
        elif operation == 'delete':
            mutated = data[:at]+data[at+count:]
        elif operation == 'replace':
            mutated = data[:at]+rng.choice(insertions)+data[at+count:]
        elif operation == 'truncate':
            mutated = data[:at]
        else:
            mutated = data[:at]+data[at:at+count]+data[at:]
        cases.append((origin, f'{operation}@{at}:{count}', mutated))
    report = dict(seed=args.seed, requested_mutations=args.samples,
                  invocation=[sys.executable, *sys.argv],
                  compiler_paths=list(map(str, compilers)), compiler_sha256=compiler_hashes,
                  std_sha256=sdk_hashes,
                  environment_overrides=dict(DYN_SDK=str(ROOT), DYN_CACHE_DIR=str(output/'cache')),
                  tool_sha256={p.name: digest(p.read_bytes()) for p in
                               (Path(__file__), HERE/'extract-tests.py', HERE/'source-cases.json',
                                HERE/'first-regressions.json')},
                  base_sources=[dict(origin=origin, sha256=digest(data)) for origin, data in bases],
                  scope='Single-file probes in an isolated directory; imports/resources may be absent. '
                        'Not an imported-project or full-language equivalence proof.',
                  cases=[])
    seen = set()
    environment = dict(os.environ, DYN_SDK=str(ROOT), DYN_CACHE_DIR=str(output/'cache'))
    with tempfile.TemporaryDirectory(prefix='dyn-acceptance-') as directory:
        source = Path(directory)/'main.dyn'
        for origin, mutation, data in cases:
            sha = digest(data)
            if sha in seen:
                continue
            seen.add(sha)
            source.write_bytes(data)
            row = dict(origin=origin, mutation=mutation, source_sha256=sha, bytes=len(data))
            for mode in ('text', 'json'):
                results = []
                for compiler in compilers:
                    command = [str(compiler), 'check', str(source.parent), '--no-cache', '--quiet']
                    if mode == 'json':
                        command += ['--diagnostics', 'json']
                    try:
                        result = subprocess.run(command, env=environment, capture_output=True, timeout=30)
                        signature = (result.returncode, result.stdout, result.stderr)
                    except subprocess.TimeoutExpired as error:
                        signature = (-1000, error.stdout or b'', (error.stderr or b'')+b'\nacceptance gate: timeout\n')
                    results.append(signature)
                invalid = any(r[0] not in (0, 1, 2) or any(marker in r[2] for marker in
                              (b'AddressSanitizer', b'LeakSanitizer', b'runtime error:')) for r in results)
                if origin == 'calibration-valid' and mutation == 'original':
                    invalid |= any(r[0] != 0 for r in results)
                if origin == 'calibration-invalid' and mutation == 'original':
                    invalid |= any(r[0] != 1 or not r[2] for r in results)
                if invalid or results[0] != results[1]:
                    (output/'failure.dyn').write_bytes(data)
                    for name, result in zip(('reference', 'candidate'), results):
                        (output/f'{name}.stdout').write_bytes(result[1])
                        (output/f'{name}.stderr').write_bytes(result[2])
                    row.update(mode=mode, returncodes=[r[0] for r in results])
                    report['failure'] = row
                    (output/'results.json').write_text(json.dumps(report, indent=2)+'\n')
                    raise AssertionError(f'acceptance/diagnostic mismatch: {row}; evidence: {output}')
                row[mode] = dict(returncode=results[0][0], stdout_sha256=digest(results[0][1]),
                                 stderr_sha256=digest(results[0][2]))
            report['cases'].append(row)
    assert compiler_hashes == [digest(p.read_bytes()) for p in compilers], 'compiler changed during gate'
    assert sdk_hashes == sdk_manifest(), 'standard library changed during gate'
    report['exit_status_counts'] = dict(Counter(row['text']['returncode'] for row in report['cases']))
    (output/'results.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'PASS {len(report["cases"])} distinct sources in text and JSON modes; '
          f'exit statuses {report["exit_status_counts"]}; {output}')


if __name__ == '__main__':
    main()
