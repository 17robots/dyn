#!/usr/bin/env python3
"""Debug builds name a failed check's line, and one type error reports once."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-check-line-') as temporary:
    program = Path(temporary) / 'program'
    subprocess.run([DYN, 'build', str(ROOT / 'tests/check-line'), '--debug', '--quiet', '--no-cache',
                    '--output', str(program)], check=True, timeout=120)
    result = subprocess.run([str(program)], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert 'in divide at ' in result.stderr and 'main.dyn:3\n' in result.stderr, result.stderr
    source = Path(temporary) / 'cascade'
    source.mkdir()
    (source / 'main.dyn').write_text('fn main() {\n  h: u64 = 1\n  b: i64 = 2\n  h = (h ^ b) * 1099511628211\n}\n')
    result = subprocess.run([DYN, 'check', str(source)], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'mismatched types' in result.stderr, result.stderr
    assert result.stderr.count('error:') == 1, result.stderr
    fault = Path(temporary) / 'fault'
    fault.mkdir()
    (fault / 'main.dyn').write_text('fn touch(address: usize) i32 {\n  return #cast(*i32, address).*\n}\nfn main() {\n  _ = touch(4096)\n}\n')
    program = Path(temporary) / 'fault-program'
    subprocess.run([DYN, 'build', str(fault), '--debug', '--quiet', '--no-cache', '--output', str(program)], check=True, timeout=120)
    result = subprocess.run([str(program)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 101 and 'memory fault' in result.stderr and 'at touch' in result.stderr, result
    # A thread's stack overflow hits its guard and reports on the thread's
    # own fault stack, on every Linux target.
    overflow = Path(temporary) / 'overflow'
    overflow.mkdir()
    (overflow / 'main.dyn').write_text('''use "std/mem"
use "std/thread"

fn down(n: u64) u64 {
  if n == 0 {
    return 0
  }
  return down(n - 1) + 1
}

fn worker(context: rawptr) isize {
  _ = context
  return #cast(isize, down(100000000))
}

fn main() {
  arena := mem.arena_alloc(0)
  spawned := thread.spawn_with_size(arena, 1048576, worker, nil)
  _ = thread.join(spawned.value)
}
''')
    for target, emulator in (('x86_64-linux', []), ('aarch64-linux', ['qemu-aarch64']), ('riscv64-linux', ['qemu-riscv64'])):
        if emulator and not shutil.which(emulator[0]):
            continue
        program = Path(temporary) / ('overflow-' + target)
        subprocess.run([DYN, 'build', str(overflow), '--target', target, '--debug', '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=120)
        result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 101 and 'memory fault' in result.stderr and '  at down (' in result.stderr, (target, result)
    windows = Path(temporary) / 'fault.exe'
    subprocess.run([DYN, 'build', str(fault), '--target', 'x86_64-windows', '--debug', '--quiet', '--no-cache', '--output', str(windows)], check=True, timeout=120)
    if shutil.which('wine'):
        result = subprocess.run(['wine', str(windows)], capture_output=True, text=True, timeout=120, env={**os.environ, 'WINEDEBUG': '-all'})
        assert result.returncode == 101 and 'memory fault' in result.stdout + result.stderr, result
    for target in ('aarch64-windows', 'aarch64-macos', 'x86_64-macos'):
        subprocess.run([DYN, 'build', str(fault), '--target', target, '--debug', '--quiet', '--no-cache', '--output', str(Path(temporary) / target)], check=True, timeout=120)
print('PASS failed checks report their line; one error reports once')
