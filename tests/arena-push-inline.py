#!/usr/bin/env python3
"""mem.push of a struct: release builds zero it with one fixed fill instead of
calling zero_bytes_fast, the memory comes back zeroed after reuse, and the
peak usage counts pushes taken by the inlined fast path across rewinds."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"
use "std/mem"

struct Node { kind: u8, flag: bool, text: []const u8, first: *Node, next: *Node, count: u64, weight: u32 }

fn make(arena: *mem.Arena, kind: u8) *Node {
  node := mem.push(Node, arena)
  node.kind = kind
  return node
}

keep_make: fn(arena: *mem.Arena, kind: u8) *Node = make

fn main() {
  arena := mem.arena_create(0)
  mark := mem.arena_mark(arena)
  // Dirty the bytes, rewind, and push over them: every field reads zero.
  dirty := mem.push_bytes_uninit(arena, 4096)
  for i in 0..#len(dirty) {
    dirty[i] = 0xab
  }
  mem.arena_rewind(arena, mark)
  total: u64 = 0
  for i in 0..100 {
    node := keep_make(arena, #cast(u8, i))
    total += #cast(u64, node.kind) + node.count + #cast(u64, node.weight) + #cast(u64, #len(node.text))
    if node.flag || node.first != nil || node.next != nil {
      total += 1000000
    }
  }
  snapshot := mem.arena_snapshot(arena)
  mem.arena_rewind(arena, mark)
  after := mem.arena_snapshot(arena)
  io.println("{} {} {} {}", total, snapshot.used, snapshot.peak_used >= 4096, after.peak_used == snapshot.peak_used)
  mem.arena_release(arena)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-arena-push-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE)
    outputs = set()
    for mode in ('--debug', '--release'):
        program = work / mode.strip('-')
        subprocess.run([DYN, 'build', str(work), mode, '--quiet', '--no-cache', '--output', str(program)], check=True, timeout=120)
        result = subprocess.run([str(program)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, (mode, result)
        outputs.add(result.stdout)
    assert outputs == {'4950 5600 true true\n'}, outputs
    if platform.system() == 'Linux' and platform.machine() == 'x86_64' and shutil.which('objdump'):
        assembly = subprocess.check_output(['objdump', '-d', '--no-show-raw-insn', str(work / 'release')], text=True)
        make = assembly.split('<make>:\n')[1].split('\n\n')[0]
        assert 'zero_bytes_fast' not in make and 'call' in make, make
print('PASS mem.push zeroes inline; peak usage counts fast pushes')
