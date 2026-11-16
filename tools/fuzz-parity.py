#!/usr/bin/env python3
"""Random-program differential: generates programs that are well typed by
construction (mixed-width integer arithmetic, shifts, guarded division,
loops, arrays, struct fields and calls), builds each in debug, release,
release --opt-level 3 and release on the tree code generator, and reports
any program whose builds print or exit differently. Arithmetic wraps in
every build, so every program has one meaning.

  tools/fuzz-parity.py [--count N] [--seed S] [--keep DIR]

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

    def condition(self, names):
        kind = self.rng.choice(list(TYPES))
        left = self.expression(kind, names, 2)
        right = self.expression(kind, names, 1)
        return f'({left} {self.rng.choice(["<", "<=", "==", "!=", ">", ">="])} {right})'

    def block(self, names, depth, indent):
        rng = self.rng
        pad = '  ' * indent
        for _ in range(rng.randrange(2, 6)):
            choice = rng.random()
            target = rng.choice([name for name in names if not name.startswith('i')] or list(names))
            kind = names[target]
            if choice < 0.5 or depth <= 0:
                operator = rng.choice(['=', '+=', '-=', '^=', '*='])
                self.lines.append(f'{pad}{target} {operator} {self.expression(kind, names, 3)}')
            elif choice < 0.65:
                self.lines.append(f'{pad}if {self.condition(names)} {{')
                self.block(names, depth - 1, indent + 1)
                self.lines.append(f'{pad}}} else {{')
                self.block(names, depth - 1, indent + 1)
                self.lines.append(f'{pad}}}')
            elif choice < 0.8:
                loop = f'i{indent}'
                self.lines.append(f'{pad}for {loop} in 0..{rng.randrange(1, 9)} {{')
                inner = dict(names)
                inner[loop] = 'u64'
                self.lines.append(f'{pad}  table[{loop} % 8] ^= #cast(u64, {self.expression(kind, inner, 2)})')
                self.block(inner, depth - 1, indent + 1)
                self.lines.append(f'{pad}}}')
            elif choice < 0.9:
                field = rng.choice(['a', 'b', 'c'])
                field_kind = {'a': 'u32', 'b': 'i64', 'c': 'u8'}[field]
                self.lines.append(f'{pad}state.{field} = {self.expression(field_kind, names, 2)}')
                self.lines.append(f'{pad}{target} ^= #cast({kind}, state.{field})')
            else:
                self.lines.append(f'{pad}{target} += #cast({kind}, mix(#cast(i64, {target}), #cast(u32, {self.expression("u32", names, 1)})))')

    def generate(self):
        rng = self.rng
        names = {f'v{i}': rng.choice(list(TYPES)) for i in range(6)}
        self.lines += ['use "std/io"', '', 'struct State { a: u32, b: i64, c: u8 }', '',
                       'fn if_greater(x: i64, y: i64) i64 {', '  if x > y { return x }', '  return y', '}', '',
                       'fn mix(x: i64, y: u32) i64 {', f'  return (x * 31 + #cast(i64, y)) ^ (x >> 7)', '}', '',
                       'fn main() {', '  table: [8]u64', '  state := State{}']
        for name, kind in names.items():
            self.lines.append(f'  {name}: {kind} = {self.literal(kind)}')
        for _ in range(rng.randrange(3, 7)):
            self.block(names, 2, 1)
            values = ', '.join(names)
            self.lines.append(f'  io.println("{" ".join("{}" for _ in names)}", {values})')
        self.lines.append('  io.println("{} {} {} {} {} {}", table[0], table[3], table[7], state.a, state.b, state.c)')
        self.lines.append('}')
        return '\n'.join(self.lines) + '\n'


def outcome(project, name, flags, env):
    program = project / name
    built = subprocess.run([DYN, 'build', str(project), *flags, '--quiet', '--no-cache', '--output', str(program)],
                           capture_output=True, text=True, timeout=600, env={**os.environ, **env})
    if built.returncode:
        return ('build failed', built.stderr[-2000:])
    try:
        run = subprocess.run([str(program)], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
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
    args = parser.parse_args()
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
