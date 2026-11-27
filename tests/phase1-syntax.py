#!/usr/bin/env python3
"""Phase 1 syntax features: significant newlines, prefix use aliases, no trailing
dot floats, backtick raw strings, header struct-literal rule, labeled break/continue,
.len, .Variant shorthand, and unified case Pattern(name) / Pattern(*name) (*T)."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())

PROGRAM = '''use out "std/io", bytes "std/bytes"

enum Color { Red, Green, Blue }

struct Vec2 { x: i32, y: i32 }

enum Shape {
  Empty,
  Circle(f64),
  Box(Vec2),
}

fn check_color(c: Color) bool {
  return c == .Green && .Green == c && c != .Red
}

fn make_color(flag: bool) Color {
  if flag { return .Blue }
  return .Red
}

fn grow(s: *Shape) {
  case s.* {
    .Empty => {}
    .Circle(*r) => { r.* += 2.5 }
    .Box(*v) => { v.x += 10 }
  }
}

fn describe(s: Shape) i32 {
  case s {
    .Empty => { return 0 }
    .Circle(r) => { return #cast(i32, r * 2.0) }
    .Box(v) => { return v.x + v.y }
  }
}

fn ignore_payload(s: Shape) i32 {
  case s {
    .Empty => { return 0 }
    .Circle(_), .Box(_) => { return 1 }
  }
}

fn inspect_any(v: any) i32 {
  case v {
    i32(n) => { return n + 1 }
    []const u8(s) => { return #cast(i32, s.len) }
    Vec2(p) => { return p.x * p.y }
    _ => { return -1 }
  }
}

const KiB: i32 = 1024

fn match_mul(n: i32) i32 {
  case n {
    2 * KiB => { return 2048 }
    _ => { return 0 }
  }
}

fn apply(f: fn (i32) i32, x: i32) i32 {
  return f(x)
}

fn inc(x: i32) i32 {
  return x + 1
}

fn bare_return_newline(flag: bool) {
  if flag {
    return
  }
}

fn main() {
  // Raw multi-line string: preserves backslashes, quotes, and newlines verbatim.
  raw := `line1\\n"quoted"
  indented line2`
  if raw.len != 32 || !bytes.contains(raw, "\\\\n") || !bytes.contains(raw, "\\n  indented") {
    #panic("raw string")
  }

  // .len on arrays, slices, pointers to arrays/slices, and string/array literals.
  arr: [3]i32 = [10, 20, 30]
  sl := arr[..]
  parr := &arr
  psl := &sl
  if arr.len != 3 || sl.len != 3 || parr.len != 3 || psl.len != 3 || "hello".len != 5 || [1, 2].len != 2 {
    #panic("len")
  }

  // .Variant shorthand in declarations, returns, comparisons, args, arrays, structs.
  c: Color = .Green
  if !check_color(c) || make_color(true) != .Blue || make_color(false) != .Red {
    #panic("enum shorthand")
  }
  palette: [2]Color = [.Red, .Blue]
  if palette[0] != .Red || palette[1] != .Blue {
    #panic("array enum shorthand")
  }

  // Unified case with real *T pointer bindings and ignored payloads.
  s: Shape = .Circle(1.5)
  grow(&s)
  if describe(s) != 8 || ignore_payload(s) != 1 {
    #panic("circle")
  }
  b: Shape = .Box(Vec2{ x: 3, y: 4 })
  grow(&b)
  if describe(b) != 17 || ignore_payload(b) != 1 {
    #panic("box")
  }

  // `any` type cases with Type(name) syntax.
  n: i32 = 41
  txt: []const u8 = "dyn"
  v := Vec2{ x: 6, y: 7 }
  if inspect_any(n) != 42 || inspect_any(txt) != 3 || inspect_any(v) != 42 {
    #panic("any case")
  }

  // Multiplication pattern in case arm (no longer hijacked by pointer binding).
  if match_mul(2048) != 2048 || match_mul(1) != 0 {
    #panic("mul case")
  }

  // Labeled break and continue.
  hits := 0
  outer: for row in 0..4 {
    for col in 0..4 {
      if col == 2 { continue outer }
      if row == 2 && col == 1 { break outer }
      hits += 1
    }
  }
  // row=0: col=0,1 (2); row=1: col=0,1 (2); row=2: col=0 (1), col=1 breaks outer => total 5
  if hits != 5 {
    #panic("labeled loops")
  }

  // Header struct literal inside parentheses.
  if (Vec2{ x: 1, y: 2 }).x != 1 {
    #panic("parenthesized header struct literal")
  }

  // Function type with space after fn, and significant-newline expression continuation.
  total := apply(inc, 10) +
    apply(inc, 20)
  if total != 32 {
    #panic("fn type / continuation")
  }

  bare_return_newline(true)
  out.println("ok phase1")
}
'''

ERRORS = {
    'use "std/io" io\nfn main() {}\n': 'import alias comes before the path',
    'fn main() {\n  x: f64 = 2.\n  _ = x\n}\n': 'float literal requires digits after decimal point',
    'fn main() {\n  xs := [1, 2]\n  _ = #len(xs)\n}\n': '#len was removed',
    'enum E { A, B: i32 }\nfn main() {}\n': 'enum payload uses parentheses',
    'enum E { A, B(i32) }\nfn main() {\n  e := E.B(1)\n  case e {\n    E.A => {}\n    E.B v => { _ = v }\n  }\n}\n': 'case bindings use parentheses',
    'fn f(v: any) {\n  case v {\n    i32 n => { _ = n }\n    _ => {}\n  }\n}\nfn main() {}\n': 'case bindings use parentheses',
    'fn main() {\n  outer: for {\n    break: outer\n  }\n}\n': 'loop labels do not use a colon',
    'fn main() {\n  outer: for {\n    outer: for {\n      break outer\n    }\n  }\n}\n': 'duplicate active loop label',
    'fn main() {\n  for {\n    break missing\n  }\n}\n': 'unknown active loop label',
    'enum Color { Red, Green }\nfn main() {\n  c := .Red\n  _ = c\n}\n': 'enum shorthand .Variant requires an expected enum type',
    'struct P { x: i32 }\nfn main() {\n  p := P{ x: 1 }\n  if p.x == P{ x: 1 }.x {}\n}\n': 'expected',
    'enum S { Empty, Num(f64) }\nfn main() {\n  s := S.Num(1.0)\n  case s {\n    S.Empty => {}\n    S.Num(*r) => { r += 1.0 }\n  }\n}\n': 'expected *f64, found f64',
}

with tempfile.TemporaryDirectory(prefix='dyn-phase1-') as temporary:
    work = Path(temporary)
    project = work / 'app'
    project.mkdir()
    (project / 'main.dyn').write_text(PROGRAM)

    # Check dyn fmt preserves raw multi-line string indentation verbatim.
    fmt_before = (project / 'main.dyn').read_text()
    subprocess.run([DYN, 'fmt', str(project)], check=True, timeout=60)
    fmt_after = (project / 'main.dyn').read_text()
    assert '`line1\\n"quoted"\n  indented line2`' in fmt_after, fmt_after

    for name, flags in (('debug', ['--debug']), ('release', ['--release'])):
        out = work / name
        subprocess.run([DYN, 'build', str(project), *flags, '--no-cache', '--quiet', '--output', str(out)],
                       check=True, timeout=120)
        res = subprocess.run([str(out)], capture_output=True, text=True, timeout=30)
        assert res.returncode == 0 and res.stdout == 'ok phase1\n', (name, res)

    for index, (source, expected) in enumerate(ERRORS.items()):
        bad = work / f'bad-{index}'
        bad.mkdir()
        (bad / 'main.dyn').write_text(source)
        res = subprocess.run([DYN, 'check', str(bad)], capture_output=True, text=True, timeout=60)
        assert res.returncode != 0 and expected in res.stderr, (index, source, expected, res.stderr)

print('PASS Phase 1 syntax features (debug/release/fmt/errors)')
