#!/usr/bin/env python3
"""Random-program differential: generates programs that are well typed by
construction (mixed-width integer arithmetic, shifts, guarded division,
loops, arrays, struct fields and calls), builds each in debug, release,
release --opt-level 3 and release on the tree code generator, and reports
any program whose builds print or exit differently. Arithmetic wraps in
every build, so every program has one meaning.

  tools/fuzz-parity.py [--count N] [--seed S] [--keep DIR] [--target T]

With --target (aarch64-linux, riscv64-linux, wasm32-wasi), the builds are
debug, release and opt-level 3 for that target, run under qemu or node.

A differing program is saved under --keep (default build/fuzz-parity) with
its outputs; tools/bisect-passes.py then names the pass behind it."""
import argparse
import concurrent.futures
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
TYPES = {'u8': (8, False), 'u16': (16, False), 'u32': (32, False), 'u64': (64, False),
         'i8': (8, True), 'i16': (16, True), 'i32': (32, True), 'i64': (64, True)}
BUILDS = (('debug', ['--debug'], {}), ('release', ['--release'], {}),
          ('o3', ['--release', '--opt-level', '3'], {}), ('tree', ['--release'], {'DYN_NO_SSA': '1'}))


class Program:
    def __init__(self, rng):
        self.rng = rng
        self.lines = []

    def literal(self, kind):
        bits, signed = TYPES[kind]
        choice = self.rng.random()
        if choice < 0.3:
            value = self.rng.randrange(0, 8)
        elif choice < 0.6:
            value = (1 << (bits - 1)) - 1 - self.rng.randrange(0, 3) if signed else (1 << bits) - 1 - self.rng.randrange(0, 3)
        else:
            value = self.rng.randrange(0, (1 << (bits - 1)) if signed else (1 << bits))
        return f'#cast({kind}, {value})'

    def expression(self, kind, names, depth):
        """An expression of type kind from names (name -> type)."""
        rng = self.rng
        same = [name for name, t in names.items() if t == kind]
        if depth <= 0 or rng.random() < 0.25:
            if same and rng.random() < 0.7:
                return rng.choice(same)
            if names and rng.random() < 0.5:
                return f'#cast({kind}, {rng.choice(list(names))})'
            return self.literal(kind)
        left = self.expression(kind, names, depth - 1)
        right = self.expression(kind, names, depth - 1)
        bits, signed = TYPES[kind]
        op = rng.choice(['+', '-', '*', '&', '|', '^', '<<', '>>', '/', '%', 'max'])
        if op in ('<<', '>>'):
            # Shift counts are unsigned; the mask keeps them below the width.
            return f'({left} {op} (#cast(u64, {right}) & {bits - 1}))'
        if op in ('/', '%'):
            # Never divide by zero or the minimum by -1: both stop the program.
            guard = f'(({right} & 15) | 1)' if not signed else f'(#cast({kind}, #cast(u64, {right}) & 15) + 1)'
            return f'({left} {op} {guard})'
        if op == 'max':
            return f'(if_greater({left}, {right}))' if kind == 'i64' else f'({left} ^ {right})'
        return f'({left} {op} {right})'

    def float_expression(self, names, depth):
        """An f64 expression: + - * / over f64 names, literals and converted integers."""
        rng = self.rng
        floats = [name for name, kind in names.items() if kind == 'f64']
        if depth <= 0 or rng.random() < 0.3:
            choice = rng.random()
            if floats and choice < 0.5:
                return rng.choice(floats)
            if choice < 0.8:
                return rng.choice(['1.5', '0.25', '-3.0', '1000000.0', '0.1', '7.0'])
            others = [name for name, kind in names.items() if kind != 'f64']
            return f'#cast(f64, {rng.choice(others)})' if others else '2.0'
        left = self.float_expression(names, depth - 1)
        right = self.float_expression(names, depth - 1)
        return f'({left} {rng.choice(["+", "-", "*", "/"])} {right})'

    def value(self, kind, names, depth):
        return self.float_expression(names, depth) if kind == 'f64' else self.expression(kind, names, depth)

    def condition(self, names):
        if self.rng.random() < 0.2:
            return f'({self.float_expression(names, 2)} {self.rng.choice(["<", ">=", "!="])} {self.float_expression(names, 1)})'
        kind = self.rng.choice(list(TYPES))
        left = self.expression(kind, names, 2)
        right = self.expression(kind, names, 1)
        return f'({left} {self.rng.choice(["<", "<=", "==", "!=", ">", ">="])} {right})'

    def block(self, names, depth, indent):
        rng = self.rng
        pad = '  ' * indent
        for _ in range(rng.randrange(2, 6)):
            choice = rng.random()
            target = rng.choice([name for name in names if not name.startswith(('i', 'k'))] or list(names))
            kind = names[target]
            integer_targets = [name for name in names if names[name] != 'f64' and not name.startswith(('i', 'k'))]
            if choice < 0.4 or depth <= 0:
                operator = rng.choice(['=', '+=', '-=', '*=']) if kind == 'f64' else rng.choice(['=', '+=', '-=', '^=', '*='])
                self.lines.append(f'{pad}{target} {operator} {self.value(kind, names, 3)}')
            elif choice < 0.5:
                self.lines.append(f'{pad}if {self.condition(names)} {{')
                self.block(names, depth - 1, indent + 1)
                self.lines.append(f'{pad}}} else {{')
                self.block(names, depth - 1, indent + 1)
                self.lines.append(f'{pad}}}')
            elif choice < 0.6:
                loop = f'i{indent}'
                self.lines.append(f'{pad}for {loop}: u64 in 0..{rng.randrange(1, 9)} {{')
                inner = dict(names)
                inner[loop] = 'u64'
                self.lines.append(f'{pad}  table[{loop} % 8] ^= #cast(u64, {self.expression("u64", inner, 2)})')
                self.block(inner, depth - 1, indent + 1)
                self.lines.append(f'{pad}}}')
            elif choice < 0.68 and integer_targets:
                # A while-style loop with continue and break.
                self.counter += 1
                counter = f'k{self.counter}'
                self.lines.append(f'{pad}{counter}: u64 = 0')
                self.lines.append(f'{pad}for {counter} < {rng.randrange(2, 12)} {{')
                self.lines.append(f'{pad}  {counter} += 1')
                inner = dict(names)
                inner[counter] = 'u64'
                self.lines.append(f'{pad}  if {self.condition(inner)} {{ continue }}')
                self.block(inner, depth - 1, indent + 1)
                self.lines.append(f'{pad}  if {self.condition(inner)} {{ break }}')
                self.lines.append(f'{pad}}}')
            elif choice < 0.76 and integer_targets:
                subject = rng.choice(integer_targets)
                self.lines.append(f'{pad}case {subject} & 3 {{')
                for arm in ('0', '1'):
                    self.lines.append(f'{pad}  {arm} => {{')
                    self.block(names, depth - 1, indent + 2)
                    self.lines.append(f'{pad}  }}')
                self.lines.append(f'{pad}  _ => {{')
                self.block(names, depth - 1, indent + 2)
                self.lines.append(f'{pad}  }}')
                self.lines.append(f'{pad}}}')
            elif choice < 0.84:
                field = rng.choice(['a', 'b', 'c'])
                field_kind = {'a': 'u32', 'b': 'i64', 'c': 'u8'}[field]
                self.lines.append(f'{pad}state.{field} = {self.expression(field_kind, names, 2)}')
                self.lines.append(f'{pad}{target} {"+=" if kind == "f64" else "^="} #cast({kind}, state.{field})')
            elif choice < 0.9:
                self.lines.append(f'{pad}adjust(&state, #cast(i64, {self.value(kind, names, 2)}))')
            elif choice < 0.95 and kind != 'f64':
                low = rng.randrange(0, 8)
                high = rng.randrange(low, 9)
                self.lines.append(f'{pad}{target} ^= #cast({kind}, total(table[{low}..{high}]))')
            elif kind != 'f64':
                self.lines.append(f'{pad}{target} += #cast({kind}, mix(#cast(i64, {target}), #cast(u32, {self.expression("u32", names, 1)})))')
            else:
                self.lines.append(f'{pad}{target} = {self.float_expression(names, 2)}')

    def generate(self):
        rng = self.rng
        self.counter = 0
        names = {f'v{i}': rng.choice(list(TYPES)) for i in range(6)}
        names['f0'] = 'f64'
        names['f1'] = 'f64'
        self.lines += ['use "std/io"', '', 'struct State { a: u32, b: i64, c: u8 }', '',
                       'fn if_greater(x: i64, y: i64) i64 {', '  if x > y { return x }', '  return y', '}', '',
                       'fn mix(x: i64, y: u32) i64 {', f'  return (x * 31 + #cast(i64, y)) ^ (x >> 7)', '}', '',
                       'fn adjust(state: *State, by: i64) {', '  state.b += by', '  if state.b > 1000 { state.b -= 777 }',
                       '  state.a ^= #cast(u32, state.b)', '}', '',
                       'fn total(values: []const u64) u64 {', '  sum: u64 = 0', '  for value in values {',
                       '    sum = sum * 31 + value', '  }', '  return sum', '}', '',
                       'fn main() {', '  table: [8]u64', '  state := State{}']
        for name, kind in names.items():
            self.lines.append(f'  {name}: {kind} = {"1.0" if kind == "f64" else self.literal(kind)}')
        for _ in range(rng.randrange(3, 7)):
            self.block(names, 2, 1)
            values = ', '.join(names)
            self.lines.append(f'  io.println("{" ".join("{}" for _ in names)}", {values})')
        self.lines.append('  io.println("{} {} {} {} {} {}", table[0], table[3], table[7], state.a, state.b, state.c)')
        self.lines.append('}')
        return '\n'.join(self.lines) + '\n'


WASI = r'''
const {WASI}=require('node:wasi'),fs=require('fs');
(async()=>{const wasi=new WASI({version:'preview1',args:['test'],returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});
'''
EMULATORS = {'aarch64-linux': ['qemu-aarch64'], 'riscv64-linux': ['qemu-riscv64'],
             'wasm32-wasi': ['node', '--no-warnings', '-e', WASI]}
TARGET = []


def outcome(project, name, flags, env):
    program = project / name
    built = subprocess.run([DYN, 'build', str(project), *flags, *TARGET, '--quiet', '--no-cache', '--output', str(program)],
                           capture_output=True, text=True, timeout=600, env={**os.environ, **env})
    if built.returncode:
        return ('build failed', built.stderr[-2000:])
    emulator = EMULATORS.get(TARGET[1], []) if TARGET else []
    try:
        run = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return ('timeout', '')
    return (run.returncode, run.stdout)


def check(seed, work):
    project = work / f'case{seed}'
    project.mkdir()
    (project / 'main.dyn').write_text(Program(random.Random(seed)).generate())
    results = {name: outcome(project, name, flags, env) for name, flags, env in BUILDS}
    return seed, project, results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--count', type=int, default=100)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--keep', type=Path, default=ROOT / 'build/fuzz-parity')
    parser.add_argument('--target')
    args = parser.parse_args()
    global BUILDS
    if args.target:
        TARGET.extend(['--target', args.target])
        BUILDS = tuple(build for build in BUILDS if build[0] != 'tree')
    differing = build_failures = 0
    with tempfile.TemporaryDirectory(prefix='dyn-fuzz-parity-') as temporary:
        seeds = range(args.seed, args.seed + args.count)
        with concurrent.futures.ThreadPoolExecutor(max(1, min(12, os.cpu_count() or 1))) as pool:
            for seed, project, results in pool.map(lambda s: check(s, Path(temporary)), seeds):
                reference = results['debug']
                if reference[0] == 'build failed':
                    build_failures += 1
                    print(f'seed {seed}: the generator wrote a program that does not compile:\n{reference[1]}')
                    continue
                if all(result == reference for result in results.values()):
                    continue
                differing += 1
                keep = args.keep / f'seed{seed}'
                shutil.rmtree(keep, ignore_errors=True)
                keep.mkdir(parents=True)
                shutil.copy(project / 'main.dyn', keep / 'main.dyn')
                for name, result in results.items():
                    (keep / f'{name}.out').write_text(f'{result[0]}\n{result[1]}')
                names = ', '.join(name for name, result in results.items() if result != reference)
                print(f'seed {seed}: {names} differ from debug; saved in {keep}')
    print(f'{args.count} programs: {differing} differ, {build_failures} did not compile')
    return 1 if differing or build_failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
