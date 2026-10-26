#!/usr/bin/env python3
"""Table-driven unwinding restores callee-saved registers across popped frames,
interleaves with handlers registered for indirect calls, and matches the
registered-handler path (DYN_NO_UNWIND_TABLES) exactly."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile

DYN = str(Path(os.environ.get('DYN', './build/dyn-release')).resolve())
SOURCE = r'''use "std/io"
use "std/fmt"
use "std/mem"
fn show(label: []const u8, value: u64) {
  storage: [64 + mem.ArenaBufferOverhead]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  _ = io.println(io.stdout(), label)
  _ = io.println(io.stdout(), fmt.u64_decimal(arena, value))
}
fn churn(seed: u64) u64 {
  // Many live values push the allocator onto callee-saved registers.
  a := seed * 3
  b := seed * 5
  c := seed * 7
  d := seed * 11
  e := seed * 13
  f := seed * 17
  if seed == 99 {
    #panic("deep panic")
  }
  r := churn(seed + 1)
  return #wrap(r + a + b + c + d + e + f)
}
fn keeper(seed: u64) u64 {
  x := seed + 1
  y := seed + 2
  z := seed + 3
  w := seed + 4
  v := seed + 5
  defer { show("keeper", x + y * 10 + z * 100 + w * 1000 + v * 10000) }
  r := churn(seed)
  return #wrap(r + x + y + z + w + v)
}
fn twice(seed: u64) u64 {
  p := seed * 2
  q := seed * 4
  defer { show("twice", p + q) }
  step: fn(u64) u64 = keeper
  return step(seed) + p + q
}
fn main() {
  k: u64 = 7
  defer { show("main", k) }
  defer { nested() }
  _ = twice(90)
}
fn nested() {
  // A cleanup that calls through frames with their own cleanup.
  defer { show("nested", 1) }
  inner()
}
fn inner() {
  m: u64 = 41
  defer { show("inner", m + 1) }
  m += 0
}
'''
EXPECTED = 'keeper\n1054311\ntwice\n540\ninner\n42\nnested\n1\nmain\n7\n'
if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'AMD64'):
    print('SKIP unwind tables: x86-64 Linux only')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-unwind-tables-') as temporary:
    root = Path(temporary)
    (root / 'main.dyn').write_text(SOURCE)
    for mode in ('debug', 'release'):
        outputs = []
        for tables in (True, False):
            environment = dict(os.environ)
            if not tables:
                environment['DYN_NO_UNWIND_TABLES'] = '1'
            program = root / f'program-{mode}-{tables}'
            subprocess.run([DYN, 'build', str(root), '--' + mode, '--no-cache', '--quiet', '--output', str(program)],
                           check=True, timeout=60, env=environment)
            sections = subprocess.run(['readelf', '-S', str(program)], capture_output=True, text=True).stdout
            assert 'dyn_unwind' in sections or not tables, mode
            result = subprocess.run([str(program)], capture_output=True, text=True, timeout=10)
            assert result.returncode == 101 and result.stdout == EXPECTED, (mode, tables, result.returncode, result.stdout)
            assert result.stderr.startswith('deep panic'), result.stderr
            outputs.append(result.stdout)
        assert outputs[0] == outputs[1]
print('PASS unwind tables: registers across popped frames, mixed registered handlers, nested cleanup (debug/release)')
