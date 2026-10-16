#!/usr/bin/env python3
"""Mutable native globals occupy zero-fill VM storage, not object-file bytes."""
import os
from pathlib import Path
import platform
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve()
TARGETS = ('x86_64-linux', 'aarch64-linux', 'riscv64-linux', 'x86_64-windows',
           'aarch64-windows', 'x86_64-macos', 'aarch64-macos')
SOURCE = '''pub arena: [1048576]u8
pub counter: u64 = 7
const marker: u64 = 31
fn main() {
  if arena[0] != 0 || arena[1048575] != 0 || counter != 7 || marker != 31 { #panic("initialization") }
  arena[1048575] = 19 counter += 2
  if arena[1048575] != 19 || counter != 9 { #panic("write") }
}
'''


def inspect(path, target):
    data = path.read_bytes()
    assert len(data) < 262144, (target, len(data))
    if target.endswith('linux'):
        table = struct.unpack_from('<Q', data, 40)[0]
        stride, count = struct.unpack_from('<HH', data, 58)
        bss = [struct.unpack_from('<IIQQQQIIQQ', data, table+i*stride)
               for i in range(count) if struct.unpack_from('<I', data, table+i*stride+4)[0] == 8]
        assert any(s[5] >= 1048576 and s[2] & 3 == 3 for s in bss), target
    elif target.endswith('windows'):
        count = struct.unpack_from('<H', data, 2)[0]
        bss = [20+i*40 for i in range(count) if struct.unpack_from('<I', data, 20+i*40+36)[0] & 0x80]
        assert any(struct.unpack_from('<II', data, at+16)[0] >= 1048576 and
                   struct.unpack_from('<II', data, at+16)[1] == 0 for at in bss), target
    else:
        count = struct.unpack_from('<I', data, 32+64)[0]
        sections = [32+72+i*80 for i in range(count)]
        bss = [at for at in sections if struct.unpack_from('<I', data, at+64)[0] & 255 == 1]
        assert len(bss) == 1, target
        address, size, offset = struct.unpack_from('<QQI', data, bss[0]+32)
        assert size >= 1048576 and offset == 0, target
        assert all(address >= sum(struct.unpack_from('<QQ', data, at+32))
                   for at in sections if at not in bss), target


with tempfile.TemporaryDirectory(prefix='dyn-native-zero-fill-') as directory:
    work = Path(directory)
    module = work/'src'
    module.mkdir()
    (module/'main.dyn').write_text(SOURCE)
    for target in TARGETS:
        for mode in ('debug', 'release'):
            output = work/f'{target}-{mode}'
            command = [str(DYN), 'build', str(module), '--'+mode, '--no-cache',
                       '--emit-object', '--target', target, '--output', str(output)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            assert result.returncode == 0, (target, mode, result.stderr)
            inspect(Path(str(output)+'.o'), target)
            if target == 'x86_64-linux' and platform.system() == 'Linux' and platform.machine() == 'x86_64':
                subprocess.run([str(output)], check=True, timeout=10)
print('PASS seven-target native zero-fill layout, debug/release linking and host initialization/write semantics')
