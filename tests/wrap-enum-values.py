#!/usr/bin/env python3
"""#wrap arithmetic and explicit enum values: behaviour, checked casts and diagnostics, debug/release."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/hash"

enum(u8) Op { Nop = 0, Add = 1, Sub, Halt = 0xFF }
enum(i8) Dir { Back = -1, Stay, Forward }
enum(u32) Chunk { None = 0, Header = 0x49484452, Data = 0x49444154 }
enum Plain { A, B, C }

seed: u32 = #wrap(4000000000 * 3)

fn expect(condition: bool, message: []const u8) {
  if !condition {
    #panic(message)
  }
}

fn name(op: Op) []const u8 {
  case op {
    Op.Nop => {
      return "nop"
    },
    Op.Add => {
      return "add"
    },
    Op.Sub => {
      return "sub"
    },
    Op.Halt => {
      return "halt"
    },
  }
}

fn main() {
  a: u8 = 250
  c: i8 = -128
  e: u8 = 0x81
  g: u8 = 3
  expect(#wrap(a + 10) == 4, "add")
  expect(#wrap(-c) == -128, "neg")
  expect(#wrap(e << 1) == 2, "shl")
  expect(#wrap(g - 4) == 255, "sub")
  expect(seed == 3410065408, "global")
  expect(hash.hash64("") == 14695981039346656037, "fnv empty")
  expect(hash.hash64("foobar") == 9625390261332436968, "fnv foobar")

  expect(#cast(u8, Op.Sub) == 2 && #cast(u8, Op.Halt) == 255, "implicit and hex values")
  expect(#cast(i32, Dir.Back) == -1 && #cast(i32, Dir.Forward) == 1, "signed values")
  expect(#cast(u32, Chunk.Data) == 0x49444154 && #cast(u32, Plain.C) == 2, "wide and plain")
  byte: u8 = 255
  expect(#cast(Op, byte) == Op.Halt && #cast(Dir, 1) == Dir.Forward, "from integer")
  expect(#len(name(#cast(Op, 2))) == 3, "case on cast value")
  wide: i64 = -1
  expect(#cast(Dir, wide) == Dir.Back, "wide signed")
}
'''
PANICS = {
  'overflow without wrap': ('a: u8 = 250\n  _ = a + 10', 'overflow.ok'),
  'wrapped division by zero': ('a: u8 = 0\n  _ = #wrap(a + 1 / a)', 'divide.ok'),
  'enum value missing': ('enum(u8) Op { Nop = 0, Add = 1, Halt = 0xFF }\nfn main() {\n  v: u16 = 3\n  _ = #cast(Op, v)', 'enum.cast.ok'),
  'enum value truncated': ('enum(u8) Op { Nop = 0, Add = 1 }\nfn main() {\n  v: u16 = 257\n  _ = #cast(Op, v)', 'enum.cast.ok'),
  'enum corrupted tag': ('enum Color { Red, Green }\nfn name(c: Color) i64 {\n  case c {\n    Color.Red => { return 1 },\n    Color.Green => { return 2 },\n  }\n}\nfn main() {\n  c: Color = Color.Red\n  bits: *u32 = #cast(*u32, #cast(rawptr, &c))\n  bits.* = 7\n  _ = name(c)', 'enum.tag.ok'),
  'enum negative unsigned': ('enum(u64) Big { Zero = 0, Top = 0xFFFFFFFFFFFFFFFF }\nfn main() {\n  v: i64 = -1\n  _ = #cast(Big, v)', 'enum.cast.ok'),
}
ERRORS = {
  'enum(u8) A { X = 256 }': 'enum value does not fit the tag type',
  'enum(u8) A { X = -1 }': 'enum value does not fit the tag type',
  'enum(i8) A { X = -129 }': 'enum value does not fit the tag type',
  'enum(u8) A { X = 0xFF, Y }': 'enum value does not fit the tag type',
  'enum A { X = 1, Y = 1 }': 'duplicate enum value',
  'enum A { X = 1, Y = 2 }': 'enum requires a variant with value 0',
  'enum(i8) A { X = -2, Y }': 'enum requires a variant with value 0',
  'enum A { X = 1, Y = 0, Z }': 'duplicate enum value',
  'enum Shape { Circle: f32 = 1, Box }': 'enums with payloads cannot have explicit values',
  'const K: u8 = 3\nenum A { X = K }': 'enum value must be an integer literal',
  'enum Shape { Circle: f32, Box }\nfn f(s: Shape) u32 {\n  return #cast(u32, s)\n}': 'cannot cast Shape to u32',
  'fn f(x: f32) f32 {\n  return #wrap(x * 2.0)\n}': '#wrap requires integer arithmetic',
  'fn f(x: u8) u8 {\n  return #wrap(x / 2)\n}': '#wrap needs +, -, * or << inside',
}


def program(directory, source):
  directory.mkdir()
  (directory / 'main.dyn').write_text(source)
  return directory


with tempfile.TemporaryDirectory(prefix='dyn-wrap-enum-') as temporary:
  work = Path(temporary)
  project = program(work / 'pass', SOURCE)
  for mode in ('--debug', '--release'):
    output = work / ('pass' + mode)
    subprocess.run([DYN, 'build', str(project), mode, '--no-cache', '--quiet', '--output', str(output)],
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
