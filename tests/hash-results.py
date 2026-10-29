#!/usr/bin/env python3
"""std/hash wyhash and CRC-32 against upstream vectors and Python oracles."""
import os
from pathlib import Path
import random
import subprocess
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
MASK = (1 << 64) - 1
SECRET = [0x2d358dccaa6c78a5, 0x8bb84b93962eacc9, 0x4b33a62ed433d4a3, 0x4d5a2da51de1aa47]
# Output of upstream test_vector.cpp (wyhash final version 4.3): message i, seed i.
UPSTREAM = [
    (b'', 10602188539874428322),
    (b'a', 14247915716899967940),
    (b'abc', 12213532920276267796),
    (b'message digest', 8677626270512586228),
    (b'abcdefghijklmnopqrstuvwxyz', 15899298861388364935),
    (b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789', 13395733826728079216),
    (b'1234567890' * 8, 7837928787916543511),
]


def mum(a, b):
    product = a * b
    return product & MASK, product >> 64


def mix(a, b):
    low, high = mum(a, b)
    return low ^ high


def read(data, at, width):
    return int.from_bytes(data[at:at + width], 'little')


def wyhash(data, seed):
    length = len(data)
    seed ^= mix(seed ^ SECRET[0], SECRET[1])
    if length <= 16:
        if length >= 4:
            shift = (length >> 3) << 2
            a = (read(data, 0, 4) << 32) | read(data, shift, 4)
            b = (read(data, length - 4, 4) << 32) | read(data, length - 4 - shift, 4)
        elif length > 0:
            a, b = (data[0] << 16) | (data[length >> 1] << 8) | data[length - 1], 0
        else:
            a = b = 0
    else:
        at, remaining = 0, length
        if remaining >= 48:
            see1 = see2 = seed
            while remaining >= 48:
                seed = mix(read(data, at, 8) ^ SECRET[1], read(data, at + 8, 8) ^ seed)
                see1 = mix(read(data, at + 16, 8) ^ SECRET[2], read(data, at + 24, 8) ^ see1)
                see2 = mix(read(data, at + 32, 8) ^ SECRET[3], read(data, at + 40, 8) ^ see2)
                at += 48
                remaining -= 48
            seed ^= see1 ^ see2
        while remaining > 16:
            seed = mix(read(data, at, 8) ^ SECRET[1], read(data, at + 8, 8) ^ seed)
            at += 16
            remaining -= 16
        a, b = read(data, at + remaining - 16, 8), read(data, at + remaining - 8, 8)
    a, b = mum(a ^ SECRET[1], b ^ seed)
    return mix(a ^ SECRET[0] ^ length, b ^ SECRET[1])


def literal(data):
    return '"' + ''.join('\\x%02x' % b for b in data) + '"'


for index, (message, expected) in enumerate(UPSTREAM):
    assert wyhash(message, index) == expected, message
rng = random.Random(64)
cases = [(message, index) for index, (message, _) in enumerate(UPSTREAM)]
cases += [(rng.randbytes(n), rng.getrandbits(64)) for n in [*range(0, 130), 255, 256, 1000, 4097]]
lines = ['use "std/hash" hash', '', 'fn check(ok: bool) {', '  if !ok {', '    #panic("hash results")', '  }', '}', '', 'fn main() {']
for data, seed in cases:
    lines.append(f'  check(hash.wyhash({literal(data)}, {seed}) == {wyhash(data, seed)})')
    lines.append(f'  check(hash.crc32({literal(data)}) == {zlib.crc32(data)})')
    cut = len(data) // 3
    lines.append(f'  check(hash.crc32_update(hash.crc32({literal(data[:cut])}), {literal(data[cut:])}) == {zlib.crc32(data)})')
lines.append('  check(hash.crc32("123456789") == 0xcbf43926)')
lines.append('}')
with tempfile.TemporaryDirectory(prefix='dyn-hash-results-') as directory:
    project = Path(directory)
    (project / 'main.dyn').write_text('\n'.join(lines) + '\n')
    for mode in ('--debug', '--release'):
        output = project / 'program'
        subprocess.run([DYN, 'build', str(project), mode, '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=300)
        subprocess.run([str(output)], check=True, timeout=60)
print('PASS hash results: wyhash upstream vectors and oracle, CRC-32 against zlib, incremental CRC-32 (debug/release)')
