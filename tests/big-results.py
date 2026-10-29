#!/usr/bin/env python3
"""std/math/big against Python integers: arithmetic, truncated division, shifts, bases, bytes, power_mod, gcd."""
import os
from pathlib import Path
import random
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
rng = random.Random(97)


def number():
    bits = rng.choice([0, 1, 31, 32, 33, 63, 64, 65, 96, 128, 200, 521, 1024, 2048])
    value = rng.getrandbits(bits) if bits else 0
    if rng.random() < 0.15 and bits:
        value = (1 << bits) - 1
    return -value if rng.random() < 0.4 else value


def trunc_div(a, b):
    q = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        q = -q
    return q, a - q * b


cases = []
for _ in range(1500):
    a, b = number(), number()
    cases.append((a, b))
cases += [(0, 0), (1, -1), (-(1 << 64), 1 << 32), ((1 << 96) - 1, (1 << 64) + 1), (12345678901234567890123, 1 << 31)]
lines = []
expected = []
for a, b in cases:
    lines.append(f'{a} {b}')
    out = [a + b, a - b, a * b]
    if b != 0:
        q, r = trunc_div(a, b)
        out += [q, r]
    else:
        out += ['none', 'none']
    shift = abs(b) % 300
    left = a << shift if a >= 0 else -((-a) << shift)
    right = a >> shift if a >= 0 else -((-a) >> shift)
    out += [left, right, (a > b) - (a < b), abs(a).bit_length()]
    out += [format(abs(a), 'x') if a >= 0 else '-' + format(-a, 'x'), format(a, 'b') if a >= 0 else '-' + format(-a, 'b')]
    out += [int.from_bytes(abs(a).to_bytes((abs(a).bit_length() + 7) // 8, 'big'), 'big')]
    import math
    out += [math.gcd(a, b)]
    modulus = abs(b)
    exponent = abs(a) % 4096
    out += [pow(a, exponent, modulus) if modulus > 0 else 'none']
    expected.append(' '.join(str(x) for x in out))
SOURCE = '''use "std/math/big" big
use "std/mem" mem
use "std/io" io
use "std/bytes" bytes

const data: []const u8 = #load("cases.txt")

fn show(arena: *mem.Arena, value: big.Int) {
  _ = io.print(io.stdout(), "{} ", big.format(arena, value, 10))
}

fn main() {
  arena := mem.arena_create(268435456)
  defer {
    mem.arena_release(arena)
  }
  at: usize = 0
  for at < #len(data) {
    end := at + bytes.find_byte(data[at..], 10)
    line := data[at..end]
    at = end + 1
    space := bytes.find_byte(line, 32)
    mark := mem.arena_mark(arena)
    a := big.parse(arena, line[..space], 10).value
    b := big.parse(arena, line[space + 1..], 10).value
    show(arena, big.add(arena, a, b))
    show(arena, big.subtract(arena, a, b))
    show(arena, big.multiply(arena, a, b))
    divided := big.divide(arena, a, b)
    if divided.ok {
      show(arena, divided.quotient)
      show(arena, divided.remainder)
    }
    else {
      _ = io.print(io.stdout(), "none none ")
    }
    shift_bits := big.divide(arena, big.absolute(b), big.from_u64(arena, 300)).remainder
    shift := big.to_u64(shift_bits).value
    show(arena, big.shift_left(arena, a, #cast(usize, shift)))
    show(arena, big.shift_right(arena, a, #cast(usize, shift)))
    _ = io.print(io.stdout(), "{} {} ", big.compare(a, b), big.bit_length(a))
    _ = io.print(io.stdout(), "{} {} ", big.format(arena, a, 16), big.format(arena, a, 2))
    show(arena, big.from_bytes(arena, big.to_bytes(arena, a)))
    show(arena, big.gcd(arena, a, b))
    exponent := big.divide(arena, big.absolute(a), big.from_u64(arena, 4096)).remainder
    powered := big.power_mod(arena, a, exponent, big.absolute(b))
    if powered.ok {
      _ = io.println(io.stdout(), "{}", big.format(arena, powered.value, 10))
    }
    else {
      _ = io.println(io.stdout(), "none")
    }
    mem.arena_rewind(arena, mark)
  }
  bad := big.parse(arena, "12x4", 10)
  if bad.ok || bad.offset != 2 {
    #panic("parse failure")
  }
  hex := big.parse(arena, "-FfeE", 16)
  if !hex.ok || !mem.equal(big.format(arena, hex.value, 36), "-1ejy") {
    #panic("bases")
  }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-big-results-') as directory:
    project = Path(directory)
    (project / 'main.dyn').write_text(SOURCE)
    (project / 'cases.txt').write_text('\n'.join(lines) + '\n')
    for mode in ('--debug', '--release'):
        output = project / 'program'
        subprocess.run([DYN, 'build', str(project), mode, '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=300)
        ran = subprocess.run([str(output)], capture_output=True, text=True, timeout=300)
        assert ran.returncode == 0, ran.stderr[-2000:]
        got = ran.stdout.splitlines()
        assert len(got) == len(expected), (len(got), len(expected))
        for line, want, case in zip(got, expected, cases):
            assert line.strip() == want, (case, line, want)
print(f'PASS big results: {len(cases)} pairs, 14 operations each, against Python integers (debug/release)')
