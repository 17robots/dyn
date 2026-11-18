#!/usr/bin/env python3
"""A loop-free helper of byte stores (binary.store_u64_le) expands in a hot
loop at O2: its literals and casts do not count against the size limit, since
the backend makes the stores one instruction."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build' / 'dyn-release')).resolve()
SOURCE = r'''use "std/encoding/binary"
use "std/io"

fn fill(destination: []u8, words: []const u64) {
  for i in 0..#len(words) {
    binary.store_u64_le(destination[i * 8..i * 8 + 8], words[i])
  }
}

fn main() {
  words: [4]u64 = [0x0807060504030201, 0x100f0e0d0c0b0a09, 1, 2]
  storage: [32]u8
  fill(storage[..], words[..])
  io.println("{} {} {}", storage[0], storage[15], storage[24])
}
'''


def main():
    if shutil.which('objdump') is None:
        print('SKIP inlining-byte-store: no objdump')
        return
    with tempfile.TemporaryDirectory(prefix='dyn-inline-store-') as temporary:
        work = Path(temporary)
        (work / 'main.dyn').write_text(SOURCE)
        program = work / 'program'
        subprocess.run([str(DYN), 'build', str(work), '--release', '--quiet', '--no-cache', '--output', str(program)], check=True,
                       timeout=120)
        output = subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=30).stdout
        assert output == '1 16 2\n', output
        listing = subprocess.run(['objdump', '-d', '--no-show-raw-insn', str(program)], capture_output=True, text=True,
                                 check=True).stdout
        calls = [line for line in listing.split('\n') if 'call' in line and 'store_u64_le' in line]
        assert not calls, calls
    print('PASS inlining-byte-store: binary.store_u64_le expands in a loop')


main()
