#!/usr/bin/env python3
"""Compare Dyn with Go, C (clang) and Odin: compile speed and memory on large
generated programs, and run time and memory on small benchmark programs.

Example: python3 tools/compare/compare.py --sizes 10000 100000 --output build/compare.json

Every language gets the same program. Scale programs come from one random seed;
benchmark programs in programs/<name>/ implement the same algorithm four times.
Compiles are fresh: Dyn uses --no-cache, and Go's cache holds only the standard
library, so every project package compiles from scratch. C files compile in
parallel, one process per file, as a build system would run them.

Go has no type-check-only command, so its "check" column is `go vet`, which also
runs vet's analyzers. Peak memory is the largest resident set of any process in
the compiler's process tree.
"""
import argparse, hashlib, json, os, platform, random, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LANGUAGES = ('dyn', 'go', 'c', 'odin')
FUNCTIONS_PER_MODULE = 40
CHAIN = 8


PEAK = None


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source_manifest(root):
    sources = {path.relative_to(root).as_posix(): sha256(path)
               for path in sorted(root.rglob('*'))
               if path.is_file() and (path.suffix in ('.dyn', '.go', '.c', '.h', '.odin')
                                      or path.name in ('go.mod', 'go.sum'))}
    return {'source_sha256': sources,
            'corpus_sha256': hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()}


def command_metadata(command, cwd=None, env=None):
    return {'command': ['bash', '-c', command] if isinstance(command, str) else command,
            'cwd': str(Path(cwd or Path.cwd()).resolve()),
            'environment_overrides': {key: env[key] for key in ('GOCACHE', 'GOFLAGS', 'GOTOOLCHAIN')
                                      if env is not None and key in env}}


def compiler_metadata():
    commands = {'dyn': os.environ.get('DYN', str(ROOT / 'build/dyn-release')),
                'go': 'go', 'c': os.environ.get('CC', 'clang'), 'odin': 'odin'}
    result = {}
    for language, command in commands.items():
        path = shutil.which(command)
        record = {'command': command, 'path': str(Path(path).resolve()) if path else None}
        try:
            record['sha256'] = sha256(path) if path else None
        except OSError as error:
            record.update(sha256=None, hash_error=str(error))
        result[language] = record
    return result


def measured(command, cwd=None, env=None):
    """Runs a command under peak.c; returns seconds, peak RSS in MiB and stdout."""
    if isinstance(command, str):
        command = ['bash', '-c', command]
    process = subprocess.run([PEAK, *command], cwd=cwd, env=env, capture_output=True, text=True)
    if process.returncode:
        raise SystemExit(f'failed: {command}\n{process.stderr[-2000:]}')
    result = json.loads(process.stderr.strip().splitlines()[-1])
    return result['seconds'], result['rss_mib'], process.stdout


# --- Generated scale programs -------------------------------------------------

def program_model(lines, seed=17):
    """Language-neutral modules: each function is loops, a branch and calls."""
    rng = random.Random(seed)
    modules, total, number = [], 0, 0
    while total < lines:
        functions = []
        for index in range(FUNCTIONS_PER_MODULE):
            loops = [(rng.randint(2, 9), rng.randint(1, 7)) for _ in range(rng.randint(1, 3))]
            branch = (rng.randint(0, 999), rng.randint(100, 9999))
            calls = rng.sample(range(index), min(index, rng.randint(0, 2)))
            functions.append((loops, branch, calls))
        previous = None if number % CHAIN == 0 else number - 1
        modules.append((previous, functions))
        total += 18 * FUNCTIONS_PER_MODULE
        number += 1
    roots = [n for n in range(len(modules)) if n % CHAIN == CHAIN - 1 or n == len(modules) - 1]
    return modules, roots


def write_dyn(root, modules, roots):
    for number, (previous, functions) in enumerate(modules):
        out = [] if previous is None else [f'use "m{previous}"', '']
        out += ['pub struct State {', '  values: [8]i64,', '  hits: i64,', '  misses: i64,', '}', '']
        for index, (loops, (limit, modulus), calls) in enumerate(functions):
            out += [f'fn f{index}(s: *State, a: i64) i64 {{', '  t: i64 = a']
            for bound, factor in loops:
                out += [f'  for i in 0..{bound} {{', f'    t += s.values[i % #len(s.values)] * {factor} + #cast(i64) i', '  }']
            out += [f'  if t > {limit} {{', '    s.hits += 1', f'    t = t % {modulus}', '  } else {', '    s.misses += 1', '  }']
            out += [f'  t += f{c}(s, t % 17)' for c in calls]
            out += ['  return t', '}', '']
        out += ['pub fn run(seed: i64) i64 {', '  s := State{}', '  for i in 0..8 {', '    s.values[i] = seed + #cast(i64) i', '  }', '  t: i64 = 0']
        out += [f'  t += f{i}(&s, seed)' for i in range(FUNCTIONS_PER_MODULE - 4, FUNCTIONS_PER_MODULE)]
        if previous is not None:
            out.append(f'  t += m{previous}.run(t % 13)')
        out += ['  return t + s.hits - s.misses', '}', '']
        (root / f'm{number}').mkdir()
        (root / f'm{number}' / f'm{number}.dyn').write_text('\n'.join(out))
    main = ['use "std/io"'] + [f'use "m{r}"' for r in roots] + ['', 'fn main() {', '  t: i64 = 0']
    main += [f'  t += m{r}.run({i})' for i, r in enumerate(roots)] + ['  _ = io.println(io.stdout(), "{}", t)', '}', '']
    (root / 'main.dyn').write_text('\n'.join(main))


def write_go(root, modules, roots):
    (root / 'go.mod').write_text('module scale\n\ngo 1.24\n')
    for number, (previous, functions) in enumerate(modules):
        out = [f'package m{number}', '']
        if previous is not None:
            out += [f'import "scale/m{previous}"', '']
        out += ['type State struct {', '\tvalues [8]int64', '\thits   int64', '\tmisses int64', '}', '']
        for index, (loops, (limit, modulus), calls) in enumerate(functions):
            out += [f'func f{index}(s *State, a int64) int64 {{', '\tt := a']
            for bound, factor in loops:
                out += [f'\tfor i := 0; i < {bound}; i++ {{', f'\t\tt += s.values[i%len(s.values)]*{factor} + int64(i)', '\t}']
            out += [f'\tif t > {limit} {{', '\t\ts.hits++', f'\t\tt = t % {modulus}', '\t} else {', '\t\ts.misses++', '\t}']
            out += [f'\tt += f{c}(s, t%17)' for c in calls]
            out += ['\treturn t', '}', '']
        out += ['func Run(seed int64) int64 {', '\ts := State{}', '\tfor i := 0; i < 8; i++ {', '\t\ts.values[i] = seed + int64(i)', '\t}', '\tt := int64(0)']
        out += [f'\tt += f{i}(&s, seed)' for i in range(FUNCTIONS_PER_MODULE - 4, FUNCTIONS_PER_MODULE)]
        if previous is not None:
            out.append(f'\tt += m{previous}.Run(t % 13)')
        out += ['\treturn t + s.hits - s.misses', '}', '']
        (root / f'm{number}').mkdir()
        (root / f'm{number}' / f'm{number}.go').write_text('\n'.join(out))
    main = ['package main', '', 'import (', '\t"fmt"'] + [f'\t"scale/m{r}"' for r in roots] + [')', '', 'func main() {', '\tt := int64(0)']
    main += [f'\tt += m{r}.Run({i})' for i, r in enumerate(roots)] + ['\tfmt.Println(t)', '}', '']
    (root / 'main.go').write_text('\n'.join(main))


def write_c(root, modules, roots):
    for number, (previous, functions) in enumerate(modules):
        (root / f'm{number}.h').write_text(f'#include <stdint.h>\nint64_t m{number}_run(int64_t seed);\n')
        out = [f'#include "m{number}.h"'] + ([f'#include "m{previous}.h"'] if previous is not None else [])
        out += ['', 'typedef struct {', '  int64_t values[8];', '  int64_t hits;', '  int64_t misses;', '} State;', '']
        out += [f'static int64_t f{i}(State *s, int64_t a);' for i in range(FUNCTIONS_PER_MODULE)] + ['']
        for index, (loops, (limit, modulus), calls) in enumerate(functions):
            out += [f'static int64_t f{index}(State *s, int64_t a) {{', '  int64_t t = a;']
            for bound, factor in loops:
                out += [f'  for (int64_t i = 0; i < {bound}; i++) {{', f'    t += s->values[i % 8] * {factor} + i;', '  }']
            out += [f'  if (t > {limit}) {{', '    s->hits += 1;', f'    t = t % {modulus};', '  } else {', '    s->misses += 1;', '  }']
            out += [f'  t += f{c}(s, t % 17);' for c in calls]
            out += ['  return t;', '}', '']
        out += [f'int64_t m{number}_run(int64_t seed) {{', '  State s = {0};', '  for (int64_t i = 0; i < 8; i++) {', '    s.values[i] = seed + i;', '  }', '  int64_t t = 0;']
        out += [f'  t += f{i}(&s, seed);' for i in range(FUNCTIONS_PER_MODULE - 4, FUNCTIONS_PER_MODULE)]
        if previous is not None:
            out.append(f'  t += m{previous}_run(t % 13);')
        out += ['  return t + s.hits - s.misses;', '}', '']
        (root / f'm{number}.c').write_text('\n'.join(out))
    main = ['#include <stdio.h>'] + [f'#include "m{r}.h"' for r in roots] + ['', 'int main(void) {', '  int64_t t = 0;']
    main += [f'  t += m{r}_run({i});' for i, r in enumerate(roots)] + ['  printf("%lld\\n", (long long)t);', '  return 0;', '}', '']
    (root / 'main.c').write_text('\n'.join(main))


def write_odin(root, modules, roots):
    for number, (previous, functions) in enumerate(modules):
        out = [f'package m{number}', '']
        if previous is not None:
            out += [f'import m{previous} "../m{previous}"', '']
        out += ['State :: struct {', '\tvalues: [8]i64,', '\thits:   i64,', '\tmisses: i64,', '}', '']
        for index, (loops, (limit, modulus), calls) in enumerate(functions):
            out += [f'f{index} :: proc(s: ^State, a: i64) -> i64 {{', '\tt := a']
            for bound, factor in loops:
                out += [f'\tfor i in 0 ..< {bound} {{', f'\t\tt += s.values[i % len(s.values)] * {factor} + i64(i)', '\t}']
            out += [f'\tif t > {limit} {{', '\t\ts.hits += 1', f'\t\tt = t % {modulus}', '\t} else {', '\t\ts.misses += 1', '\t}']
            out += [f'\tt += f{c}(s, t % 17)' for c in calls]
            out += ['\treturn t', '}', '']
        out += ['run :: proc(seed: i64) -> i64 {', '\ts := State{}', '\tfor i in 0 ..< 8 {', '\t\ts.values[i] = seed + i64(i)', '\t}', '\tt: i64 = 0']
        out += [f'\tt += f{i}(&s, seed)' for i in range(FUNCTIONS_PER_MODULE - 4, FUNCTIONS_PER_MODULE)]
        if previous is not None:
            out.append(f'\tt += m{previous}.run(t % 13)')
        out += ['\treturn t + s.hits - s.misses', '}', '']
        (root / f'm{number}').mkdir()
        (root / f'm{number}' / f'm{number}.odin').write_text('\n'.join(out))
    main = ['package main', '', 'import "core:fmt"'] + [f'import m{r} "m{r}"' for r in roots] + ['', 'main :: proc() {', '\tt: i64 = 0']
    main += [f'\tt += m{r}.run({i})' for i, r in enumerate(roots)] + ['\tfmt.println(t)', '}', '']
    (root / 'main.odin').write_text('\n'.join(main))


WRITERS = {'dyn': write_dyn, 'go': write_go, 'c': write_c, 'odin': write_odin}


def count_lines(root):
    return sum(len(p.read_text().splitlines()) for p in root.rglob('*') if p.suffix in ('.dyn', '.go', '.c', '.h', '.odin'))


class Tools:
    def __init__(self, work, jobs):
        self.dyn = os.environ.get('DYN', str(ROOT / 'build/dyn-release'))
        self.jobs = jobs
        self.gocache = work / 'gocache-std'
        env = self.go_env(self.gocache)
        hello = work / 'go-warm'
        hello.mkdir()
        (hello / 'go.mod').write_text('module warm\n\ngo 1.24\n')
        (hello / 'main.go').write_text('package main\n\nimport "fmt"\n\nfunc main() { fmt.Println(1) }\n')
        for flags in ([], ['-gcflags=all=-N -l']):
            subprocess.run(['go', 'build', *flags, '-o', str(work / 'warm'), '.'], cwd=hello, env=env, check=True)
        subprocess.run(['go', 'vet', '.'], cwd=hello, env=env, check=True)

    def go_env(self, cache):
        return {**os.environ, 'GOCACHE': str(cache), 'GOFLAGS': '-mod=mod', 'GOTOOLCHAIN': 'local'}

    def fresh_go_env(self, work):
        cache = Path(tempfile.mkdtemp(dir=work, prefix='gocache-'))
        shutil.rmtree(cache)
        shutil.copytree(self.gocache, cache)
        return self.go_env(cache)

    def commands(self, language, root, output, mode, work):
        """Returns (command, env) for mode in check/debug/release."""
        if language == 'dyn':
            base = [self.dyn, 'check' if mode == 'check' else 'build', str(root), '--no-cache', '--quiet']
            if mode != 'check':
                base += ['--output', str(output)] + (['--release'] if mode == 'release' else [])
            return base, None
        if language == 'go':
            env = self.fresh_go_env(work)
            if mode == 'check':
                return ['go', 'vet', './...'], env
            flags = ['-gcflags=all=-N -l'] if mode == 'debug' else []
            return ['go', 'build', *flags, '-o', str(output), '.'], env
        if language == 'c':
            cc = os.environ.get('CC', 'clang')
            if mode == 'check':
                return f'ls *.c | xargs -P {self.jobs} -n 1 {cc} -fsyntax-only', None
            flags = '-O0 -g' if mode == 'debug' else '-O2'
            objects = work / f'c-{mode}-objects-{output.name}'
            objects.mkdir()
            return (f'ls *.c | xargs -P {self.jobs} -I{{}} sh -c \'{cc} {flags} -c {{}} -o {objects}/$(basename {{}} .c).o\''
                    f' && {cc} {objects}/*.o -o {output}'), None
        if language == 'odin':
            if mode == 'check':
                return ['odin', 'check', '.'], None
            flags = ['-o:none', '-debug'] if mode == 'debug' else ['-o:speed']
            return ['odin', 'build', '.', f'-out:{output}', *flags], None
        raise ValueError(language)


def scale(tools, sizes, work, languages):
    results = []
    for lines in sizes:
        modules, roots = program_model(lines)
        expected = None
        for language in languages:
            root = work / f'scale-{lines}-{language}'
            root.mkdir()
            WRITERS[language](root, modules, roots)
            row = {'lines': count_lines(root), 'target_lines': lines, 'language': language,
                   **source_manifest(root), 'commands': {}, 'generator_seed': 17}
            for mode in ('check', 'debug', 'release'):
                output = work / f'scale-{lines}-{language}-{mode}'
                command, env = tools.commands(language, root, output, mode, work)
                row['commands'][mode] = command_metadata(command, root, env)
                seconds, rss, _ = measured(command, cwd=root, env=env)
                row[mode] = {'seconds': round(seconds, 3), 'rss_mib': round(rss, 1)}
                if mode != 'check':
                    # Correctness gate stays outside compilation measurements.
                    run_command = [str(output)]
                    row['commands'][mode + '_run'] = command_metadata(run_command, root)
                    try:
                        execution = subprocess.run(run_command, cwd=root, capture_output=True,
                                                   text=True, check=True, timeout=120)
                    except (OSError, subprocess.SubprocessError) as error:
                        raise SystemExit(f'scale {lines}: {language} {mode} execution failed: {error}') from error
                    actual = execution.stdout.strip()
                    row[mode]['output'] = actual
                    if expected is None:
                        expected = actual
                    elif actual != expected:
                        raise SystemExit(f'scale {lines}: {language} {mode} printed {actual!r}, expected {expected!r}')
                print(f'scale {lines:>8} {language:<4} {mode:<7} {seconds:8.2f}s {rss:8.1f} MiB', flush=True)
            results.append(row)
    return results


def benchmarks(tools, work, languages, runs):
    results = []
    for program in sorted(p.name for p in (HERE / 'programs').iterdir() if p.is_dir()):
        expected = None
        for language in languages:
            source = HERE / 'programs' / program
            root = work / f'bench-{program}-{language}'
            root.mkdir()
            suffix = {'dyn': 'dyn', 'go': 'go', 'c': 'c', 'odin': 'odin'}[language]
            shutil.copy(source / f'main.{suffix}', root / f'main.{suffix}')
            if language == 'go':
                (root / 'go.mod').write_text('module bench\n\ngo 1.24\n')
            manifest = source_manifest(root)
            output = work / f'bench-{program}-{language}-bin'
            command, env = tools.commands(language, root, output, 'release', work)
            if language == 'c':
                command = [os.environ.get('CC', 'clang'), '-O2', 'main.c', '-o', str(output)]
            build_seconds, build_rss, _ = measured(command, cwd=root, env=env)
            best, peak, out = None, 0.0, ''
            for _ in range(runs):
                seconds, rss, out = measured([str(output)])
                best = seconds if best is None else min(best, seconds)
                peak = max(peak, rss)
                out = out.strip()
                if expected is None:
                    expected = out
                elif out != expected:
                    raise SystemExit(f'{program}: {language} printed {out!r}, expected {expected!r}')
            results.append({'program': program, 'language': language, 'run_seconds': round(best, 3),
                            'run_rss_mib': round(peak, 1), 'build_seconds': round(build_seconds, 3),
                            'build_rss_mib': round(build_rss, 1), **manifest,
                            'commands': {'build': command_metadata(command, root, env),
                                         'run': command_metadata([str(output)])},
                            'runs': runs,
                            'binary_kib': round(output.stat().st_size / 1024, 1), 'output': out})
            print(f'bench {program:<10} {language:<4} {best:7.3f}s {peak:8.1f} MiB  binary {output.stat().st_size // 1024} KiB', flush=True)
    return results


def versions():
    def first(command):
        try:
            return subprocess.run(command, capture_output=True, text=True).stdout.strip().splitlines()[0]
        except (OSError, IndexError):
            return 'missing'
    return {'dyn': first([os.environ.get('DYN', str(ROOT / 'build/dyn-release')), 'version']),
            'go': first(['go', 'version']), 'c': first([os.environ.get('CC', 'clang'), '--version']),
            'odin': first(['odin', 'version'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--sizes', type=int, nargs='*', default=[10000, 100000, 500000])
    parser.add_argument('--languages', nargs='*', default=list(LANGUAGES), choices=LANGUAGES)
    parser.add_argument('--runs', type=int, default=3, help='runs per benchmark; the fastest counts')
    parser.add_argument('--skip-benchmarks', action='store_true')
    parser.add_argument('--jobs', type=int, default=os.cpu_count())
    parser.add_argument('--output', type=Path, default=ROOT / 'build/compare.json')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='dyn-compare-') as temporary:
        work = Path(temporary)
        global PEAK
        PEAK = str(work / 'peak')
        peak_command = ['cc', '-O2', str(HERE / 'peak.c'), '-o', PEAK]
        subprocess.run(peak_command, check=True)
        tools = Tools(work, args.jobs)
        report = {'versions': versions(), 'cpus': os.cpu_count(),
                  'host': {'platform': platform.platform(), 'machine': platform.machine(),
                           'processor': platform.processor(), 'python': platform.python_version()},
                  'compilers': compiler_metadata(), 'compare_sha256': sha256(Path(__file__)),
                  'peak': {'source_sha256': sha256(HERE / 'peak.c'), 'binary_sha256': sha256(PEAK),
                           'build': command_metadata(peak_command), 'precision_mib': 0.1,
                           'scope': 'Linux RUSAGE_CHILDREN maximum individual-process RSS, including reaped descendants; not simultaneous process-tree memory'},
                  'jobs': args.jobs, 'runs': args.runs, 'invocation': [sys.executable, *sys.argv],
                  'scale': scale(tools, args.sizes, work, args.languages)}
        if not args.skip_benchmarks:
            report['benchmarks'] = benchmarks(tools, work, args.languages, args.runs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'wrote {args.output}')


if __name__ == '__main__':
    main()
