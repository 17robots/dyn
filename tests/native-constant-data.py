#!/usr/bin/env python3
"""Constant globals that hold addresses are read-only once loaded.

They need relocations, so the object places them in .data.rel.ro (ELF),
__DATA,__const (Mach-O) or .rdata (COFF). Writing through a pointer to one
must fault in executables and shared libraries.
"""
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve()
LIBRARY = '''struct Pair { a: u64, b: u64 }
fn plus(x: u64) u64 { return x + 1 }
const frozen: Pair = Pair{a: 10, b: 20}
const frozen_callback: fn(u64) u64 = plus
pub fn frozen_pointer() rawptr { return #cast(rawptr, &frozen) }
pub fn frozen_total() u64 { return frozen.a + frozen.b + frozen_callback(1) }
'''
PROGRAM = LIBRARY + '''fn main() {
  if frozen_total() != 32 { #panic("constant values") }
  pointer := #cast(*u64, frozen_pointer())
  pointer.* = 0
}
'''


def build(root, source, output, *flags):
    root.mkdir(parents=True, exist_ok=True)
    (root/'main.dyn').write_text(source)
    subprocess.run([DYN, 'build', root, '--no-cache', '--quiet', '--output', output, *flags],
                   check=True, timeout=120)


def faults(command):
    # qemu writes core files into the working directory.
    result = subprocess.run(command, capture_output=True, timeout=30, cwd=Path(command[-1]).parent)
    return result.returncode in (-11, 139) or b'Segmentation fault' in result.stderr


def macho_constant_segment(path):
    data = path.read_bytes()
    count, offset = struct.unpack_from('<I', data, 16)[0], 32
    for _ in range(count):
        command, size = struct.unpack_from('<II', data, offset)
        if command == 0x19:
            segment = data[offset+8:offset+24].rstrip(b'\0').decode()
            sections = struct.unpack_from('<I', data, offset+64)[0]
            names = [data[offset+72+80*i:offset+88+80*i].rstrip(b'\0').decode() for i in range(sections)]
            if '__const' in names and segment != '__TEXT':
                return segment, struct.unpack_from('<I', data, offset+68)[0]
        offset += size
    return None


def main():
    native = sys.platform.startswith('linux') and platform.machine() in ('x86_64', 'amd64')
    with tempfile.TemporaryDirectory(prefix='dyn-constant-data-') as directory:
        work = Path(directory)
        checks = 0
        if native:
            for mode in ('--debug', '--release'):
                executable = work/('program' + mode)
                build(work/'program', PROGRAM, executable, mode)
                assert faults([executable]), mode
                library = work/('library' + mode + '.so')
                build(work/'library', LIBRARY, library, mode, '--shared')
                script = ('import ctypes,sys;lib=ctypes.CDLL(sys.argv[1]);lib.frozen_total.restype=ctypes.c_uint64;'
                          'assert lib.frozen_total()==32;lib.frozen_pointer.restype=ctypes.c_void_p;'
                          'ctypes.c_uint64.from_address(lib.frozen_pointer()).value=0')
                assert faults([sys.executable, '-c', script, library]), mode
                checks += 2
        for target, runner in (('aarch64-linux', 'qemu-aarch64'), ('riscv64-linux', 'qemu-riscv64')):
            if not native or not shutil.which(runner):
                continue
            executable = work/target
            build(work/'program', PROGRAM, executable, '--release', '--target', target)
            assert faults([runner, executable]), target
            checks += 1
        for target in ('aarch64-macos', 'x86_64-macos'):
            executable = work/target
            build(work/'program', PROGRAM, executable, '--release', '--target', target)
            found = macho_constant_segment(executable)
            assert found == ('__DATA_CONST', 0x10), (target, found)
            checks += 1
    print(f'PASS read-only constant data: {checks} executables, libraries and Mach-O layouts')


if __name__ == '__main__':
    main()
