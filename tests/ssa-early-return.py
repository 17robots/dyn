#!/usr/bin/env python3
"""Early returns run before the prologue.

ssa_early_return follows a path from the entry through blocks without
effects to a return and emits it ahead of the prologue, straight from the
argument registers: loads go to scratch registers, checks and branches off
the path jump to the regular entry. The program covers a recursive base
case, a tree walk whose test loads through a checked pointer, a void
function's guard, a return of an argument plus a constant after a
register comparison, and a function whose entry calls before testing
(no early path). Every build prints what the tree emitter prints."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"

struct Node {
  left: *Node,
  right: *Node
}

sink: u64 = 0

fn note(x: u64) u64 {
  sink += x
  return x
}

fn fib(n: i64) i64 {
  if n < 2 {
    return n
  }
  return fib(n - 1) + fib(n - 2)
}

fn count(node: *Node) i64 {
  if node.left == nil {
    return 1
  }
  return 1 + count(node.left) + count(node.right)
}

fn walk(values: []u64, depth: u64) {
  if #len(values) < 2 {
    return
  }
  sink += values[0] * depth
  walk(values[1..], depth + 1)
  sink += note(depth)
}

fn bounded(n: u64, limit: u64) u64 {
  if n > limit {
    return limit + 3
  }
  return bounded(n + 1, limit) + note(n)
}

fn noted(n: u64) u64 {
  if note(n) == 0 {
    return 9
  }
  return noted(n - 1) + 1
}

fn main() {
  leaves: [8]Node
  inner: [7]Node
  for i in 0..8 {
    leaves[i] = Node{left: nil, right: nil}
  }
  for i in 0..4 {
    inner[i] = Node{left: &leaves[2 * i], right: &leaves[2 * i + 1]}
  }
  inner[4] = Node{left: &inner[0], right: &inner[1]}
  inner[5] = Node{left: &inner[2], right: &inner[3]}
  inner[6] = Node{left: &inner[4], right: &inner[5]}
  values: [6]u64
  for i in 0..6 {
    values[i] = #cast(u64, i) * 3 + 1
  }
  walk(values[..], 1)
  walk(values[5..], 1)
  io.println("{} {} {} {} {} {}", fib(20), count(&inner[6]), bounded(2, 9), noted(4), sink, fib(1))
}
'''
EARLY = ('fib', 'count', 'walk', 'bounded')
with tempfile.TemporaryDirectory(prefix='dyn-ssa-early-return-') as temporary:
    source = Path(temporary) / 'main.dyn'
    source.write_text(SOURCE)
    expected = None
    for target, emulator, disassembler in (('x86_64-linux', [], ['objdump']), ('aarch64-linux', ['qemu-aarch64'], ['llvm-objdump']),
                                           ('riscv64-linux', ['qemu-riscv64'], None), ('x86_64-windows', ['wine'], None)):
        for name, env in (('tree', {'DYN_NO_SSA': '1'}), ('ssa', {'DYN_NO_INLINE': '1'}), ('inlined', {})):
            program = Path(temporary) / f'{target}-{name}{".exe" if "windows" in target else ""}'
            subprocess.run([DYN, 'build', str(source), '--release', '--target', target, '--no-cache', '--quiet',
                            '--output', str(program)], check=True, timeout=120, env={**os.environ, **env})
            if name == 'ssa' and disassembler and shutil.which(disassembler[0]):
                listing = subprocess.run([*disassembler, '-d', '--no-show-raw-insn', str(program)], capture_output=True,
                                         text=True, check=True).stdout
                prologue = r'\tpush\s+%rbp' if target == 'x86_64-linux' else r'\tstp\tx29, x30'
                for function in (*EARLY, 'noted'):
                    body = re.search(rf'<{function}>:\n(.*?)\n\n', listing, re.S).group(1)
                    ret, push = re.search(r'\tret', body), re.search(prologue, body)
                    assert ret and push, (target, function, body)
                    assert (ret.start() < push.start()) == (function in EARLY), (target, function, body)
            if emulator and not shutil.which(emulator[0]):
                continue
            result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=60,
                                    env={**os.environ, 'WINEDEBUG': '-all'})
            assert result.returncode == 0, (target, name, result)
            output = result.stdout.replace('\r\n', '\n')
            expected = expected or output
            assert output == expected, (target, name, output, expected)
print('PASS early returns: base cases, checked loads and guards return before the prologue; outputs match on every target')
