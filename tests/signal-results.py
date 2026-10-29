#!/usr/bin/env python3
"""std/process/signal: queued SIGINT, SIGTERM and SIGHUP on Linux; watch, poll and close under wine."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/process/signal" signal
use "std/io" io
use "std/errors" errors

fn check(ok: bool) {
  if !ok {
    #panic("signal results")
  }
}

fn main() {
  zero: signal.Watch
  check(signal.poll(&zero).kind == errors.Kind.InvalidState)
  check(signal.close(&zero).ok)
  check(signal.watch(signal.Set{}).kind == errors.Kind.InvalidInput)
  opened := signal.watch(signal.Set{ interrupt: true, terminate: true, hangup: HANGUP })
  check(opened.ok)
  state := opened.value
  first := signal.poll(&state)
  check(first.ok && first.value == signal.Kind.None)
  if WAIT {
    _ = io.println(io.stdout(), "ready")
    for i in 0..3 {
      next := signal.wait(&state)
      check(next.ok)
      _ = io.println(io.stdout(), "{}", #cast(u32, next.value))
    }
  }
  check(signal.close(&state).ok && !state.active)
  _ = io.println(io.stdout(), "closed")
}
'''


def build(directory, target, wait):
    project = Path(directory) / f'{target}-{wait}'
    project.mkdir()
    hangup = 'true' if 'windows' not in target else 'false'
    source = SOURCE.replace('HANGUP', hangup).replace('WAIT', 'true' if wait else 'false')
    (project / 'main.dyn').write_text(source)
    output = project / 'program'
    subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--target', target, '--output', str(output)], check=True, timeout=120)
    return output


with tempfile.TemporaryDirectory(prefix='dyn-signal-results-') as directory:
    for target in ('aarch64-linux', 'riscv64-linux', 'aarch64-macos', 'x86_64-macos', 'aarch64-windows'):
        program = build(directory, target, False)
        # User-mode QEMU checks the translated signalfd and mask syscalls.
        emulator = {'aarch64-linux': 'qemu-aarch64', 'riscv64-linux': 'qemu-riscv64'}.get(target)
        if emulator and shutil.which(emulator) and sys.platform == 'linux':
            result = subprocess.run([emulator, str(program)], capture_output=True, text=True, timeout=60)
            assert result.returncode == 0 and 'closed' in result.stdout, result
    if sys.platform == 'linux' and os.uname().machine == 'x86_64':
        program = build(directory, 'x86_64-linux', True)
        process = subprocess.Popen([str(program)], stdout=subprocess.PIPE, text=True)
        assert process.stdout.readline().strip() == 'ready'
        # Queued while the program is waiting, read back in order.
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            process.send_signal(number)
            line = process.stdout.readline().strip()
            assert line == {signal.SIGINT: '1', signal.SIGTERM: '2', signal.SIGHUP: '3'}[number], line
        assert process.stdout.readline().strip() == 'closed'
        assert process.wait(timeout=30) == 0
    if shutil.which('wine'):
        program = build(directory, 'x86_64-windows', False)
        result = subprocess.run(['wine', str(program)], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0 and 'closed' in result.stdout, result
print('PASS signal results: queued interrupt/terminate/hangup, poll, wait and close; six cross-builds')
