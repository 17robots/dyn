#!/usr/bin/env python3
"""Bare-metal stack guards, using the QEMU wrapper conventions in bare-metal.py.

DYN selects the compiler; DYN_QEMU_RISCV64, DYN_QEMU_RISCV32 and DYN_QEMU_ARM
select optional command wrappers. Container wrappers must mount TMPDIR at the
same path and bound the guest lifetime (for example, timeout 50).
"""
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())

# Reading the local array after the recursive call keeps the frame live and
# makes this non-tail recursion, including in release builds.
RECURSION = '''use "std/io"

fn descend(depth: usize) u8 {
  frame: [4096]u8
  for i in 0..#len(frame) { frame[i] = #cast(u8, i % 251) }
  if depth == 0 { return frame[0] }
  child := descend(depth - 1)
  return frame[#cast(usize, child)]
}

fn main() {
  result := descend(1000000)
  _ = io.write_all(io.stdout(), "unexpected return\\n")
  _ = result
}
'''

FRAME = '''use "std/io"

fn fill(bytes: []u8) {
  for i in 0..#len(bytes) { bytes[i] = #cast(u8, i % 251) }
}

fn main() {
  frame: [SIZE]u8
  fill(frame[..])
  if frame[0] == 0 && frame[SIZE - 1] == #cast(u8, (SIZE - 1) % 251) {
    _ = io.write_all(io.stdout(), "frame ok\\n")
  }
}
'''

TARGETS = (
    ('riscv32-none-soft', 'DYN_QEMU_RISCV32', 'qemu-system-riscv32',
     ['-machine', 'virt', '-cpu', 'sifive-e31', '-bios', 'none']),
    ('thumbv7em-none-soft', 'DYN_QEMU_ARM', 'qemu-system-arm',
     ['-machine', 'mps2-an500', '-semihosting-config', 'enable=on,target=native']),
    ('riscv64-none', 'DYN_QEMU_RISCV64', 'qemu-system-riscv64',
     ['-machine', 'virt', '-bios', 'none']),
    ('riscv32-none', 'DYN_QEMU_RISCV32', 'qemu-system-riscv32',
     ['-machine', 'virt', '-bios', 'none']),
    ('thumbv7em-none', 'DYN_QEMU_ARM', 'qemu-system-arm',
     ['-machine', 'mps2-an500', '-semihosting-config', 'enable=on,target=native']),
)
CASES = (
    ('recursion', RECURSION, 104, b'stack overflow\n'),
    ('huge-frame', FRAME.replace('SIZE', '2097152'), 104, b'stack overflow\n'),
    ('modest-frame', FRAME.replace('SIZE', '4096'), 0, b'frame ok\n'),
)


def run_guest(command):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise AssertionError(f'QEMU guest did not exit within 60 seconds: {command}')
    return process.returncode, output


def main():
    failures = []
    for target, variable, program, board in TARGETS:
        qemu = shlex.split(os.environ.get(variable, '')) or ([program] if shutil.which(program) else [])
        with tempfile.TemporaryDirectory(prefix='dyn-bare-stack-') as temporary:
            work = Path(temporary)
            for name, source, expected_status, expected_output in CASES:
                project = work / name
                project.mkdir()
                (project / 'main.dyn').write_text(source)
                for release in (False, True):
                    label = f'{target} {name} {"release" if release else "debug"}'
                    image = work / f'{name}-{"release" if release else "debug"}'
                    try:
                        subprocess.run([DYN, 'build', str(project), '--target', target,
                                        '--no-cache', '--quiet', '--output', str(image)]
                                       + (['--release'] if release else []), check=True, timeout=120)
                        if not qemu:
                            print(f'PASS {label} build (SKIP running: {program} not found)', flush=True)
                            continue
                        status, output = run_guest([*qemu, *board, '-nographic', '-kernel', str(image)])
                        output = output.replace(b'\r\n', b'\n')
                        assert (status, output) == (expected_status, expected_output), (
                            f'expected exit {expected_status}, {expected_output!r}; '
                            f'got exit {status}, {output[:65536]!r}')
                        print(f'PASS {label}', flush=True)
                    except (AssertionError, subprocess.SubprocessError) as error:
                        failures.append(f'{label}: {error}')
                        print(f'FAIL {failures[-1]}', flush=True)
    if failures:
        raise SystemExit('\n'.join(failures))


if __name__ == '__main__':
    main()
