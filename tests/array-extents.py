#!/usr/bin/env python3
"""Constant fixed-array lengths, import interfaces, and rejected runtime sizes."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())

with tempfile.TemporaryDirectory(prefix='dyn-array-extents-') as temporary:
    project = Path(temporary)
    (project / 'layout').mkdir()
    (project / 'layout/main.dyn').write_text('''const Width: usize = 4
const Height: usize = Half + 1
pub struct Grid { data: [Width * Height]u8 }
pub fn grid() Grid { return Grid{} }
''')
    (project / 'layout/constants.dyn').write_text('''const Half: usize = 2
fn private_callback() {}
const UnusedCallback: *fn() = &private_callback
''')
    source = project / 'main.dyn'
    source.write_text('''use "std/mem"
use "./layout"
const Later: usize = Base + 1
const Base: usize = 2
type Row = [Later]u8
fn main() {
  const Local: usize = 5
  bytes: [4 * mem.KiB]u8 = []
  local: [(Local + 1) * 2]u8 = []
  rows: [2]Row = []
  grid := layout.grid()
  if #len(bytes) != 4096 || #len(local) != 12 || #sizeof(rows) != 6 || #sizeof(grid) != 12 {
    #panic("constant array extent")
  }
  bytes[4095] = 42
  if bytes[4095] != 42 { #panic("constant array access") }
}
''')
    for release in (False, True):
        output = project / ('release' if release else 'debug')
        for cache in (['--no-cache'], []):
            subprocess.run([DYN, 'build', str(project), '--quiet', '--output', str(output),
                            *cache, *(['--release'] if release else [])], check=True, timeout=120)
            subprocess.run([str(output)], check=True, timeout=10)

    # Changing a private layout constant must invalidate cached dependent layout.
    layout = project / 'layout/main.dyn'
    layout.write_text(layout.read_text().replace('Width: usize = 4', 'Width: usize = 5'))
    source.write_text(source.read_text().replace('#sizeof(grid) != 12', '#sizeof(grid) != 15'))
    output = project / 'changed-layout'
    subprocess.run([DYN, 'build', str(project), '--quiet', '--output', str(output)], check=True, timeout=120)
    subprocess.run([str(output)], check=True, timeout=10)

    invalid = [
        'use "./layout"\nfn main() { _ = layout.Width }',
        'fn main() { count := 4 data: [count]u8 = [] _ = data }',
        'fn f(count: usize) { data: [count]u8 = [] _ = data } fn main() {}',
        'const N: usize = M const M: usize = N fn main() { data: [N]u8 = [] _ = data }',
        'fn main() { data: [1 - 2]u8 = [] _ = data }',
        'fn main() { data: [1 / 0]u8 = [] _ = data }',
        'fn main() { data: [18446744073709551615 + 1]u8 = [] _ = data }',
        'fn main() { data: [1.5]u8 = [] _ = data }',
        'const N: f64 = 4 fn main() { data: [N]u8 = [] _ = data }',
        'fn main() { data: [1 << 64]u8 = [] _ = data }',
        'fn main() { data: [N]u8 = [] const N: usize = 2 _ = data }',
    ]
    for code in invalid:
        source.write_text(code)
        result = subprocess.run([DYN, 'check', str(project), '--diagnostics', 'json', '--no-cache'],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 1, (code, result.returncode, result.stderr)
        assert 'error' in result.stderr, (code, result.stderr)
print('PASS constant array lengths, imported layout, cache, and invalid extents (debug/release)')
