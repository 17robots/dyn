#!/usr/bin/env python3
"""Generate a synthetic multi-module Dyn project for compiler throughput tests.

The shape imitates ordinary programs: many modules, each with a struct and a
call tree of small and medium functions. No function calls more than a handful
of others, so optimizer cost scales with program size rather than with one
pathological function.

Example: python3 tools/generate-scale.py --lines 100000 build/scale-100k

--helpers generic|concrete adds min/max helpers called about once per 400
lines (raddbg's density for Min/Max), written as generics or as i64
functions, to measure the cost of instantiation.
"""
import argparse, random
from pathlib import Path

FUNCTIONS_PER_MODULE = 40


HELPERS = {
    'generic': """pub fn min(a, b: $T) T {
  if a < b { return a }
  return b
}

pub fn max(a, b: $T) T {
  if a > b { return a }
  return b
}
""",
    'concrete': """pub fn min(a, b: i64) i64 {
  if a < b { return a }
  return b
}

pub fn max(a, b: i64) i64 {
  if a > b { return a }
  return b
}
""",
}


def function(rng, module, index, helpers):
    name = f'f{index}'
    lines = [f'fn {name}(s: *State, a: i64) i64 {{', '  t: i64 = a']
    if helpers and rng.random() < 0.05:
        lines.append(f'  t = helpers.{rng.choice(("min", "max"))}(t, {rng.randint(1, 999)})')
    for j in range(rng.randint(1, 3)):
        bound = rng.randint(2, 9)
        lines += [
            f'  for i in 0..{bound} {{',
            f'    t += s.values[i % #len(s.values)] * {rng.randint(1, 7)} + #cast(i64) i',
            '  }',
        ]
    lines += [
        f'  if t > {rng.randint(0, 999)} {{',
        '    s.hits += 1',
        f'    t = t % {rng.randint(100, 9999)}',
        '  } else {',
        f'    s.misses += 1',
        '  }',
    ]
    for callee in rng.sample(range(index), min(index, rng.randint(0, 2))):
        lines.append(f'  t += f{callee}(s, t % 17)')
    lines += ['  return t', '}']
    return lines


def module(rng, number, previous, helpers):
    lines = ['use "helpers"'] if helpers else []
    if previous is not None:
        lines.append(f'use "m{previous}"')
    lines += ['', 'pub struct State {', '  values: [8]i64,', '  hits: i64,', '  misses: i64,', '}', '']
    for index in range(FUNCTIONS_PER_MODULE):
        lines += function(rng, number, index, helpers)
        lines.append('')
    lines += ['pub fn run(seed: i64) i64 {', '  s := State{}', '  for i in 0..8 {', '    s.values[i] = seed + #cast(i64) i', '  }', '  t: i64 = 0']
    for index in range(FUNCTIONS_PER_MODULE - 4, FUNCTIONS_PER_MODULE):
        lines.append(f'  t += f{index}(&s, seed)')
    if previous is not None:
        lines.append(f'  t += m{previous}.run(t % 13)')
    lines += ['  return t + s.hits - s.misses', '}', '']
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--lines', type=int, default=100000)
    parser.add_argument('--chain', type=int, default=8, help='modules per dependency chain')
    parser.add_argument('--seed', type=int, default=17)
    parser.add_argument('--helpers', choices=sorted(HELPERS))
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output exists; choose a new directory')
    rng = random.Random(args.seed)
    args.output.mkdir(parents=True)
    total, number, roots = 0, 0, []
    while total < args.lines:
        previous = None if number % args.chain == 0 else number - 1
        lines = module(rng, number, previous, args.helpers)
        directory = args.output / f'm{number}'
        directory.mkdir()
        (directory / f'm{number}.dyn').write_text('\n'.join(lines))
        total += len(lines)
        if number % args.chain == args.chain - 1:
            roots.append(number)
        number += 1
    if (number - 1) not in roots:
        roots.append(number - 1)
    main_lines = ['use "std/io"'] + [f'use "m{r}"' for r in roots]
    main_lines += ['', 'fn main() {', '  t: i64 = 0']
    main_lines += [f'  t += m{r}.run({i})' for i, r in enumerate(roots)]
    main_lines += ['  _ = io.println(io.stdout(), "{}", t)', '}', '']
    (args.output / 'main.dyn').write_text('\n'.join(main_lines))
    if args.helpers:
        (args.output / 'helpers').mkdir()
        (args.output / 'helpers/helpers.dyn').write_text(HELPERS[args.helpers])
    print(f'{total + len(main_lines)} lines in {number} modules')


if __name__ == '__main__':
    main()
