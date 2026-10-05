#!/usr/bin/env python3
"""Panic messages survive local cleanup and caller-frame unwinding."""
import os
from pathlib import Path
import subprocess
import tempfile

DYN = str(Path(os.environ.get('DYN', './build/dyn-release')).resolve())
cases = {
    'bounds': '''use "std/io"
fn checked(index: usize) u8 { values: [1]u8 = [7] return values[index] }
fn main() { defer { _ = io.println(io.stdout(), "cleanup") } _ = checked(2) }''',
    'direct': 'fn main() { #panic("owned panic message") }',
    'local': '''use "std/io"\nuse "std/mem"
fn main() {
  owned := mem.arena_create(64)
  if !owned.ok { #panic("allocation") }
  defer { _ = mem.arena_release(&owned.arena) _ = io.println(io.stdout(), "cleanup") }
  text := mem.arena_push_or_panic(&owned.arena, 32, 1)[..32]
  _ = mem.copy(text, "owned panic message")
  #panic(text[..19])
}''',
    'caller': '''use "std/io"\nuse "std/mem"
fn fail(text: []const u8) { #panic(text) }
fn main() {
  owned := mem.arena_create(64)
  if !owned.ok { #panic("allocation") }
  defer { _ = mem.arena_release(&owned.arena) _ = io.println(io.stdout(), "cleanup") }
  text := mem.arena_push_or_panic(&owned.arena, 32, 1)[..32]
  _ = mem.copy(text, "owned panic message")
  fail(text[..19])
}''',
}
cases['nested-cleanup'] = cases['caller'].replace(
    '_ = io.println(io.stdout(), "cleanup")', 'cleanup()') + '''
fn cleanup() {
  defer { _ = io.println(io.stdout(), "cleanup") }
  _ = io.println(io.stdout(), "nested cleanup call")
}
'''
cases['bounded'] = '''use "std/io"
fn main() {
  text: [6000]u8 = []
  index: usize = 0 for index < 6000 { text[index] = 120 index += 1 }
  defer { _ = io.println(io.stdout(), "cleanup") }
  #panic(text[..])
}
'''
cases['unicode-bound'] = ('use "std/io"\nfn main() { '
    'defer { _ = io.println(io.stdout(), "cleanup") } #panic("' +
    'x' + '🙂' * 1100 + '") }\n')
with tempfile.TemporaryDirectory(prefix='dyn-panic-lifetime-') as temporary:
    root = Path(temporary)
    for name, source in cases.items():
        (root / 'main.dyn').write_text(source, encoding='utf-8')
        for mode in ('debug', 'release'):
            if name == 'bounds' and mode == 'release':
                continue
            output = root / ('program.exe' if os.name == 'nt' else 'program')
            built = subprocess.run([DYN, 'build', str(root), '--'+mode, '--no-cache',
                                    '--jobs', '1', '--output', str(output)], capture_output=True, text=True, encoding='utf-8', timeout=30)
            assert built.returncode == 0, built.stderr
            result = subprocess.run([str(output)], capture_output=True, text=True, encoding='utf-8', timeout=5)
            assert result.returncode == 101, (name, mode, result.returncode, result.stderr)
            if name != 'direct':
                assert 'cleanup' in result.stdout, (name, mode, result.stdout)
            if name == 'bounds':
                assert 'runtime check failed (index.ok) in checked' in result.stderr, result.stderr
            elif name == 'bounded':
                first = result.stderr.splitlines()[0]
                assert len(first) == 4096 and first.endswith(' [truncated]'), (name, mode, len(first))
            elif name == 'unicode-bound':
                first = result.stderr.splitlines()[0]
                assert first.startswith('x🙂') and first.endswith(' [truncated]')
                assert len(first.encode()) <= 4096
            else:
                assert 'owned panic message' in result.stderr, (name, mode, result.stderr)
print('PASS panic message ownership across local/caller cleanup, debug/release')
