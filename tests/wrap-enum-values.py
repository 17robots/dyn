#!/usr/bin/env python3
"""Wrapping arithmetic and dense enums: behaviour and diagnostics, debug/release."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/enums"
use "std/hash"

enum(u8) Op { Nop, Add, Sub, Halt }
enum(i8) Dir { Back, Stay, Forward }
enum Plain { A, B, C }

seed: u32 = 4000000000

fn expect(condition: bool, message: []const u8) {
  if !condition {
    #panic(message)
  }
}

fn name(op: Op) []const u8 {
  case op {
    Op.Nop => {
      return "nop"
    }
    Op.Add => {
      return "add"
    }
    Op.Sub => {
      return "sub"
    }
    Op.Halt => {
      return "halt"
    }
  }
}

fn main() {
  a: u8 = 250
  c: i8 = -128
  e: u8 = 0x81
  g: u8 = 3
  expect(a + 10 == 4, "add")
  expect(-c == -128, "neg")
  expect(e << 1 == 2, "shl")
  expect(g - 4 == 255, "sub")
  expect(seed * 3 == 3410065408, "global")
  count: u8 = 9
  expect(g << count == 6, "masked shift")
  expect(hash.hash64("") == 14695981039346656037, "fnv empty")
  expect(hash.hash64("foobar") == 9625390261332436968, "fnv foobar")

  expect(#cast(u8, Op.Sub) == 2 && #cast(u8, Op.Halt) == 3, "dense values")
  expect(#cast(i32, Dir.Forward) == 2 && #cast(u32, Plain.C) == 2, "signed and plain")
  byte: u8 = 3
  expect(enums.from_int(Op, byte) == Op.Halt, "from integer")
  expect(#len(name(enums.from_int(Op, 2))) == 3, "case on converted value")
  expect(enums.from_int(Op, 200) == Op.Nop, "unknown tag gives the first variant")
}
'''
PANICS = {
  'division by zero': ('a: u8 = 0\n  _ = 1 / a', 'divide.ok'),
  'enum corrupted tag': ('enum Color { Red, Green }\nfn name(c: Color) i64 {\n  case c {\n    Color.Red => { return 1 }\n    Color.Green => { return 2 }\n  }\n}\nfn main() {\n  c: Color = Color.Red\n  bits: *u32 = #cast(*u32, #cast(rawptr, &c))\n  bits.* = 7\n  _ = name(c)', 'enum.tag.ok'),
}
ERRORS = {
  'enum A { X = 1, Y }': 'first enum variant must be 0',
  'enum Shape { Circle: f32, Box }': 'first enum variant has no payload',
  'fn f() u8 {\n  return #wrap(1)\n}': 'each statement',
  'const K: u8 = 255 + 1': 'overflows',
}


def program(directory, source):
  directory.mkdir()
  (directory / 'main.dyn').write_text(source)
  return directory


with tempfile.TemporaryDirectory(prefix='dyn-wrap-enum-') as temporary:
  work = Path(temporary)
  project = program(work / 'pass', SOURCE)
  # The program checks wrapping itself, so debug builds opt out of overflow checks.
  for mode in ('--debug', '--release'):
    output = work / ('pass' + mode)
    flags = ['--no-check-overflow'] if mode == '--debug' else []
    subprocess.run([DYN, 'build', str(project), mode, *flags, '--no-cache', '--quiet', '--output', str(output)],
                   cwd=ROOT, check=True, timeout=120)
    subprocess.run([str(output)], check=True, timeout=10)
  for index, (label, (body, check)) in enumerate(PANICS.items()):
    source = body if body.startswith('enum') else 'fn main() {\n  ' + body
    project = program(work / f'panic{index}', source + '\n}\n')
    for mode in ('--debug', '--release'):
      output = work / f'panic{index}{mode}'
      subprocess.run([DYN, 'build', str(project), mode, '--no-cache', '--quiet', '--output', str(output)],
                     cwd=ROOT, check=True, timeout=120)
      result = subprocess.run([str(output)], capture_output=True, text=True, timeout=10)
      assert result.returncode != 0 and check in result.stderr, (label, mode, result.returncode, result.stderr)
  for index, (source, message) in enumerate(ERRORS.items()):
    project = program(work / f'error{index}', source + '\nfn main() {\n}\n')
    result = subprocess.run([DYN, 'check', str(project)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode != 0 and message in result.stdout + result.stderr, (source, result.stdout, result.stderr)
print('PASS #wrap arithmetic and explicit enum values, casts and diagnostics (debug/release)')
