#!/usr/bin/env python3
"""A child started by std/process does not inherit the signals a
std/process/signal watch blocks in its parent."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
TARGETS = ('x86_64-linux', 'aarch64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows')

PROGRAM = '''use io "std/io"
use mem "std/mem"
use process "std/process"
use signal "std/process/signal"
fn main() {
  arena := mem.arena_alloc(1 << 20)
  watch := signal.watch(signal.Set{ interrupt: true, terminate: true, hangup: true }) catch { #panic("watch") }
  defer signal.close(&watch)
  arguments: [3][]const u8 = ["sh", "-c", "grep SigBlk /proc/self/status"]
  captured := process.capture(arena, "/bin/sh", arguments[..], process.Options{}, process.CaptureOptions{}) catch { #panic("capture") }
  io.println("{}", captured.output)
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-signal-mask-') as directory:
    root = Path(directory)
    (root / 'main.dyn').write_text(PROGRAM)
    for target in TARGETS:
        checked = subprocess.run([DYN, 'check', str(root), '--quiet', '--target', target], capture_output=True, text=True)
        assert checked.returncode == 0, (target, checked.stderr)
    if sys.platform.startswith('linux'):
        program = root / 'program'
        built = subprocess.run([DYN, 'build', str(root), '--quiet', '--no-cache', '--output', str(program)], capture_output=True, text=True)
        assert built.returncode == 0, built.stderr
        ran = subprocess.run([str(program)], capture_output=True, text=True, timeout=30)
        assert ran.returncode == 0, ran.stderr
        line = ran.stdout.strip()
        assert line.startswith('SigBlk:') and int(line.split()[1], 16) == 0, line
print('PASS process signal mask: children start with no blocked signals; six targets check')
