#!/usr/bin/env python3
"""Preferred global storage alignment without changing source type layout.

Checks actual object headers/symbols (including cross targets), linked ELF
addresses, and exact runtime behavior. Set DYN to an isolated compiler to test.
No timing measurements or external object inspection tools are needed.
"""
import os
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
ENV = dict(os.environ, DYN_SDK=str(ROOT))


def inspect(path):
    data = path.read_bytes()
    def unpack(fmt, at):
        return struct.unpack_from('<' + fmt, data, at)
    def string(at):
        return data[at:data.index(0, at)].decode()
    sections, symbols = {}, {}
    if data[:4] == b'\x7fELF':
        wide = data[4] == 2
        if wide:
            shoff = unpack('Q', 40)[0]
            stride, count = unpack('HH', 58)
        else:
            shoff = unpack('I', 32)[0]
            stride, count = unpack('HH', 46)
        headers = [unpack('IIQQQQIIQQ' if wide else '10I', shoff + i * stride)
                   for i in range(count)]
        for i, h in enumerate(headers):
            # address, file offset, byte size, alignment, section kind
            sections[i] = (h[3], h[4], h[5], h[8], h[1])
        for h in headers:
            if h[1] != 2:
                continue
            strings = headers[h[6]][4]
            for at in range(h[4], h[4] + h[5], h[9]):
                if wide:
                    name, info, other, section, value, size = unpack('IBBHQQ', at)
                else:
                    name, value, size, info, other, section = unpack('IIIBBH', at)
                if section and (info & 15) == 1:
                    symbols[string(strings + name)] = (section, value, size)
        return 'ELF', sections, symbols
    if data[:4] == b'\xcf\xfa\xed\xfe':
        cursor, symbol_at, symbol_count, strings = 32, 0, 0, 0
        for _ in range(unpack('I', 16)[0]):
            command, size = unpack('II', cursor)
            if command == 0x19:
                for i in range(unpack('I', cursor + 64)[0]):
                    at = cursor + 72 + 80 * i
                    address, length, offset, exponent = unpack('QQII', at + 32)
                    sections[len(sections) + 1] = (address, offset, length, 1 << exponent,
                                                  unpack('I', at + 64)[0] & 255)
            elif command == 2:
                symbol_at, symbol_count, strings = unpack('III', cursor + 8)
            cursor += size
        for i in range(symbol_count):
            name, kind, section, desc, value = unpack('IBBHQ', symbol_at + 16 * i)
            if section:
                symbols[string(strings + name).removeprefix('_')] = (section, value, None)
        return 'MachO', sections, symbols
    # COFF: symbol values are section-relative; alignment is encoded in flags.
    _, count, _, symoff, symcount, optional, _ = unpack('HHIIIHH', 0)
    strings = symoff + 18 * symcount
    for i in range(count):
        at = 20 + optional + 40 * i
        length, offset = unpack('II', at + 16)
        flags = unpack('I', at + 36)[0]
        sections[i + 1] = (0, offset, length, 1 << (((flags >> 20) & 15) - 1),
                           8 if flags & 0x80 else 1)
    i = 0
    while i < symcount:
        at = symoff + 18 * i
        name = (string(strings + unpack('I', at + 4)[0]) if data[at:at + 4] == b'\0' * 4
                else data[at:at + 8].rstrip(b'\0').decode())
        value, section, kind, storage, aux = unpack('IhHBB', at + 8)
        if section > 0:
            symbols[name] = (section, value, None)
        i += 1 + aux
    return 'COFF', sections, symbols


SIZES = {'bytes': 17, 'matrix': 4 * 9 * 8, 'values': 24,
         'tiny': 15, 'threshold': 16, 'initialized': 24, 'holder': 19, 'preceding': None}


def check(path, preceding, linked=False):
    kind, sections, symbols = inspect(path)
    header = path.read_bytes()[:5]
    word = 4 if header[:4] == b'\x7fELF' and header[4] == 1 else 8
    for name, size in SIZES.items():
        size = 4 * word if size == 'pointers' else size
        section, value, actual_size = symbols[name]
        address, offset, length, alignment, section_kind = sections[section]
        if actual_size is not None:
            assert actual_size == (preceding if size is None else size), (path, name, actual_size)
        if name in ('bytes', 'matrix', 'values', 'threshold', 'initialized'):
            assert value % 16 == 0, (path, name, 'symbol', value)
            assert alignment >= 16, (path, name, 'section alignment', alignment)
            assert address % 16 == 0, (path, name, 'section address', address)
            if section_kind not in (8, 1 if kind == 'MachO' else -1):
                assert offset % 16 == 0, (path, name, 'section file offset', offset)
        if not linked:
            relative = value - address if kind == 'MachO' else value
            assert relative + (preceding if size is None else size) <= length, (path, name, 'capacity')
    # Padding may separate objects; it must never consume their capacities.
    for section in sections:
        spans = sorted((value, value + (preceding if SIZES[name] is None else SIZES[name]))
                       for name in SIZES for sec, value, _ in [symbols[name]] if sec == section)
        assert all(end <= following for (_, end), (following, _) in zip(spans, spans[1:])), path
    # Constant data must retain all values, even when its start is padded.
    section, value, _ = symbols['values']
    address, offset, _, _, _ = sections[section]
    relative = value - address if linked or kind == 'MachO' else value
    assert struct.unpack_from('<3q', path.read_bytes(), offset + relative) == (11, 13, 17), path


def source(preceding):
    return f'''use "std/io"
pub preceding: [{preceding}]u8
pub bytes: [17]u8
pub matrix: [4][9]i64
pub tiny: [15]u8
pub threshold: [16]u8
pub initialized: [3]i64 = [19, 23, 29]
pub const const_prefix: u8 = 3
pub const values: [3]i64 = [11, 13, 17]
struct Holder {{ tag: u8, data: [17]u8, tail: u8 }}
pub holder: Holder
fn increment(value: usize) usize {{ return value + 1 }}
pub const pointers: [4]fn(usize) usize = [increment, increment, increment, increment]
fn main() {{
  if #sizeof([17]u8) != 17 || #alignof([17]u8) != 1 ||
     #alignof([4][9]i64) != 8 || #sizeof(Holder) != 19 ||
     #alignof(Holder) != 1 {{ #panic("source layout changed") }}
  if initialized[0] != 19 || initialized[1] != 23 || initialized[2] != 29 {{ #panic("initializer") }}
  preceding[0] = 7
  tiny[14] = 5
  threshold[15] = 9
  holder.tag = 2
  holder.data[16] = 4
  holder.tail = 6
  checksum: i64 = 0
  i: usize = 0
  for i < 4 {{
    j: usize = 0
    for j < 9 {{
      matrix[i][j] = #cast(i64, i * 9 + j + 1)
      checksum += matrix[i][j]
      j += 1
    }}
    i += 1
  }}
  bytes[16] = 8
  if pointers[0](6) != 7 || pointers[1](7) != 8 || pointers[2](8) != 9 || pointers[3](4) != 5 {{ #panic("constant array relocations") }}
  checksum += values[0] + values[1] + values[2] + #cast(i64,
    preceding[0] + tiny[14] + threshold[15] + bytes[16] + holder.tag + holder.data[16] + holder.tail + const_prefix)
  if checksum != 751 {{ #panic("checksum") }}
  _ = io.write_all(io.stdout(), "751\\n")
}}
'''


def main():
    # Multiple residues force padding both before arrays and after odd capacities.
    targets = ('x86_64-linux', 'aarch64-linux', 'riscv64-linux',
               'riscv32-none', 'thumbv7em-none', 'x86_64-macos',
               'aarch64-macos', 'x86_64-windows', 'aarch64-windows')
    with tempfile.TemporaryDirectory(prefix='global-alignment-', dir=ROOT / 'build') as tmp:
        work = Path(tmp)
        src = work / 'source'
        src.mkdir()
        count = 0
        for preceding in (1, 8, 17, 24):
            (src / 'main.dyn').write_text(source(preceding))
            for mode in ('--debug', '--release'):
                for target in targets:
                    output = work / f'{preceding}-{mode[2:]}-{target}'
                    subprocess.run([DYN, 'build', str(src), '--quiet', '--no-cache',
                                    mode, '--target', target, '--emit-object', '--no-link',
                                    '--output', str(output)], cwd=ROOT, env=ENV, check=True)
                    check(Path(str(output) + '.o'), preceding)
                    count += 1
                output = work / f'run-{preceding}-{mode[2:]}'
                subprocess.run([DYN, 'build', str(src), '--quiet', '--no-cache', mode,
                                '--target', 'x86_64-linux', '--output', str(output)], cwd=ROOT, env=ENV, check=True)
                check(output, preceding, linked=True)
                result = subprocess.run([str(output)], capture_output=True, text=True, check=True)
                assert result.stdout == '751\n', result
        print(f'PASS global alignment: {count} cross-target objects, 8 linked address/checksum probes')


if __name__ == '__main__':
    main()
