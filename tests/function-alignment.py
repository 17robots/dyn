#!/usr/bin/env python3
"""x86 function entries are packed at every optimization level.

Optimized builds once aligned entries to 64 bytes at --opt-level 2 and 3 but
not under plain --release, which optimizes at the same level. Measured kernels
moved by -10% to +9% with placement and gained nothing consistent, so every
mode now uses the section's ordinary alignment and plain --release lays code
out exactly like --opt-level 2."""
import os
from pathlib import Path
import platform
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve()
SOURCE = '''extern fn external "external"(x: u64) u64
pub fn first(x: u64) u64 { return x + 1 }
pub fn second(x: u64) u64 { return x * 3 }
pub fn recursive(x: u64) u64 { if x < 2 { return x }
return recursive(x-1)+recursive(x-2) }
pub fn foreign_call(x: u64) u64 { return external(x) }
'''
NAMES = {'first', 'second', 'recursive', 'foreign_call'}


def run(*args):
    result = subprocess.run(list(map(str, args)), cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result


def elf(data):
    table = struct.unpack_from('<Q', data, 40)[0]
    stride, count = struct.unpack_from('<HH', data, 58)
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, table+i*stride) for i in range(count)]
    entries, foreign = {}, {}
    for section in sections:
        if section[1] != 2:
            continue
        strings = sections[section[6]]
        names = data[strings[4]:strings[4]+strings[5]]
        for at in range(section[4], section[4]+section[5], section[9]):
            name, info, _, index, value, size = struct.unpack_from('<IBBHQQ', data, at)
            label = names[name:].split(b'\0', 1)[0].decode()
            if index == 0:
                foreign[label] = (value, size)
            elif info & 15 == 2:
                entries[label] = value
    return sections[1][8], entries, foreign


def coff(data):
    _, count, _, table, symbols = struct.unpack_from('<HHIII', data)
    sections = [struct.unpack_from('<8sIIIIIIHHI', data, 20+40*i) for i in range(count)]
    alignment = 1 << (((sections[0][9] >> 20) & 15)-1)
    strings = table+18*symbols
    entries, foreign, i = {}, {}, 0
    while i < symbols:
        at = table+18*i
        raw, value, section, kind, _, auxiliary = struct.unpack_from('<8sIhHBB', data, at)
        if raw[:4] == b'\0'*4:
            offset = struct.unpack_from('<I', raw, 4)[0]
            label = data[strings+offset:].split(b'\0', 1)[0].decode()
        else:
            label = raw.rstrip(b'\0').decode()
        if section == 1 and kind & 0x20:
            entries[label] = value
        elif section == 0:
            foreign[label] = (value, 0)
        i += 1+auxiliary
    return alignment, entries, foreign


def macho(data):
    count = struct.unpack_from('<I', data, 16)[0]
    at, alignment, text_address, table = 32, None, None, None
    for _ in range(count):
        command, size = struct.unpack_from('<II', data, at)
        if command == 0x19:
            section = at+72
            assert data[section:section+16].rstrip(b'\0') == b'__text'
            text_address, _, offset, power = struct.unpack_from('<QQII', data, section+32)
            alignment = 1 << power
            assert offset % alignment == 0 and text_address % alignment == 0
        elif command == 2:
            table = struct.unpack_from('<IIII', data, at+8)
        at += size
    symbols, count, strings, _ = table
    entries, foreign = {}, {}
    for i in range(count):
        name, kind, section, _, value = struct.unpack_from('<IBBHQ', data, symbols+16*i)
        label = data[strings+name:].split(b'\0', 1)[0].decode().removeprefix('_')
        if section == 1 and kind & 0x0e == 0x0e:
            entries[label] = value-text_address
        elif section == 0:
            foreign[label] = (value, 0)
    return alignment, entries, foreign


with tempfile.TemporaryDirectory(prefix='dyn-function-alignment-') as directory:
    work = Path(directory)
    module = work/'module'
    module.mkdir()
    (module/'main.dyn').write_text(SOURCE)
    for target, parser, baseline in [('x86_64-linux', elf, 16), ('x86_64-windows', coff, 16), ('x86_64-macos', macho, 4)]:
        objects = {}
        for mode, flags in [('release', ['--release']),
                            ('o2', ['--release', '--opt-level', '2']),
                            ('o3', ['--release', '--opt-level', '3']),
                            ('o1', ['--release', '--opt-level', '1']),
                            ('debug', ['--debug']),
                            ('dwarf', ['--release', '--opt-level', '3', '--debug-info'])]:
            output = work/(target+'-'+mode)
            run(DYN, 'build', module, '--backend', 'native', '--shared', '--no-link', '--emit-object',
                '--no-cache', '--quiet', '--target', target, '--output', output, *flags)
            data = output.with_suffix('.o').read_bytes()
            objects[mode] = data
            alignment, entries, foreign = parser(data)
            assert alignment == baseline, (target, mode, alignment, baseline)
            assert NAMES <= entries.keys(), (target, mode, entries)
            assert foreign['external'] == (0, 0), (target, mode, foreign)
        assert objects['release'] == objects['o2'], (target, 'plain --release differs from --opt-level 2')
    if platform.system() == 'Linux' and platform.machine() in ('x86_64', 'amd64'):
        (module/'main.dyn').write_text(SOURCE.split('pub fn foreign_call')[0].replace('extern fn external "external"(x: u64) u64\n', '')+
                                       'callbacks: [3]fn(u64) u64 = [first, second, recursive]\nfn main() { if callbacks[2](12) != 144 || callbacks[0](8) != 9 || callbacks[1](8) != 24 { #panic("packed calls") } }\n')
        output = work/'linked'
        run(DYN, 'build', module, '--release', '--opt-level', '3', '--no-cache', '--quiet', '--output', output)
        run(output)
print('PASS x86 function entries packed at every level; plain --release matches --opt-level 2')
