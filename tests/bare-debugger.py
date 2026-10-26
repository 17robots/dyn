#!/usr/bin/env python3
"""Check 32-bit DWARF layouts and live frames through QEMU's GDB server."""
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''struct Pair { x: u32, y: u32 }
fn inner(a: u32, label: []const u8) u32 {
  total := a + 2
  pair := Pair{x: a, y: total}
  _ = pair
  return total
}
fn outer(a: u32) u32 {
  return inner(a, "hello")
}
fn main() {
  result := outer(40)
  if result != 42 { #panic("wrong result") }
}
'''
TARGETS = (
    ('riscv32-none', 'DYN_QEMU_RISCV32', 'qemu-system-riscv32', ['-machine', 'virt', '-bios', 'none']),
    ('riscv32-none-soft', 'DYN_QEMU_RISCV32', 'qemu-system-riscv32', ['-machine', 'virt', '-cpu', 'sifive-e31', '-bios', 'none']),
    ('thumbv7em-none', 'DYN_QEMU_ARM', 'qemu-system-arm', ['-machine', 'mps2-an500', '-semihosting-config', 'enable=on,target=native']),
    ('thumbv7em-none-soft', 'DYN_QEMU_ARM', 'qemu-system-arm', ['-machine', 'mps2-an500', '-semihosting-config', 'enable=on,target=native']),
)
for target, variable, program, board in TARGETS:
    with tempfile.TemporaryDirectory(prefix='dyn-bare-dwarf-') as directory:
        root = Path(directory)
        app = root / 'app'
        app.mkdir()
        (app / 'main.dyn').write_text(SOURCE)
        image = root / 'app.elf'
        subprocess.run([DYN, 'build', str(app), '--target', target, '--debug-info', '--quiet',
                        '--no-cache', '--output', str(image)], check=True, timeout=120)
        if shutil.which('llvm-dwarfdump'):
            checked = subprocess.run(['llvm-dwarfdump', '--verify', str(image)], capture_output=True, text=True, timeout=30)
            assert checked.returncode == 0, checked.stdout + checked.stderr
        if shutil.which('readelf'):
            info = subprocess.check_output(['readelf', '--debug-dump=info', str(image)], text=True)
            assert 'Pointer Size:  4' in info, info
            assert re.search(r'DW_TAG_pointer_type\).*?DW_AT_byte_size\s*:\s*4', info, re.S), info
            pcs = re.findall(r'DW_AT_low_pc\s*:\s*(0x[0-9a-f]+)', info)
            assert pcs and all(int(pc, 16) % 2 == 0 for pc in pcs), pcs
            frames = subprocess.check_output(['readelf', '--debug-dump=frames', str(image)], text=True)
            assert ('r11 ofs 4132' if target.startswith('thumb') else 'r8') in frames, frames
        runner = shlex.split(os.environ.get(variable, '')) or ([program] if shutil.which(program) else [])
        if not runner or not shutil.which('gdb'):
            print(f'PASS {target} DWARF structure (SKIP live debugger: QEMU/GDB unavailable)')
            continue
        socket = root / 'gdb.sock'
        guest = subprocess.Popen([*runner, *board, '-nographic', '-kernel', str(image), '-S',
                                  '-gdb', f'unix:{socket},server=on,wait=off'],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
        try:
            deadline = time.monotonic() + 15
            while not socket.exists() and guest.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert socket.exists(), guest.stderr.read().decode() if guest.poll() is not None else 'GDB socket did not appear'
            commands = ['set debuginfod enabled off', f'target remote {socket}', 'break main.dyn:6',
                        'continue', 'info args', 'info locals', 'print pair.y', 'print label.len',
                        'print sizeof(label)', 'print sizeof(label.data)', 'backtrace',
                        'echo BEFORE_FINISH\\n', 'finish', 'echo AFTER_FINISH\\n',
                        'frame', 'backtrace', 'echo END_FINISH\\n', 'detach']
            session = subprocess.run(['gdb', '-batch', '-nx', str(image),
                                      *[part for command in commands for part in ('-ex', command)]],
                                     capture_output=True, text=True, timeout=30)
            output = session.stdout + session.stderr
            for expected in ('total = 42', 'pair = {x = 40, y = 42}', '$1 = 42', '$2 = 5',
                             '$3 = 8', '$4 = 4', 'in outer (a=40)', 'in main ()'):
                assert expected in output, (target, expected, output)
            after_finish = output.split('AFTER_FINISH\n', 1)[-1].split('END_FINISH\n', 1)[0]
            assert 'AFTER_FINISH\n' in output and 'END_FINISH\n' in output, output
            assert re.search(r'^#0\s+.*\bouter \(a=40\)', after_finish, re.M), output
            assert not re.search(r'^#\d+\s+.*\binner \(', after_finish, re.M), output
            assert session.returncode == 0, output
        finally:
            if guest.poll() is None:
                os.killpg(guest.pid, signal.SIGKILL)
            guest.communicate(timeout=10)
        print(f'PASS {target} live debugger: parameters, locals, string layout, nested frames and return')
