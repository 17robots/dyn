#!/usr/bin/env python3
"""ARM ELF flags and AEABI file attributes agree, including unflagged Clang.

Encoding/defaults: ARM-software/abi-aa addenda32, build attributes.
DYN and CLANG override the compilers. No emulator is required.
"""
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
CLANG = shlex.split(os.environ.get('CLANG', 'clang'))


def sections(data):
    offset, = struct.unpack_from('<I', data, 32)
    size, count = struct.unpack_from('<HH', data, 46)
    return [(offset + i * size, struct.unpack_from('<10I', data, offset + i * size))
            for i in range(count)]


def vendor(payload, name=b'aeabi'):
    return struct.pack('<I', 5 + len(name) + len(payload)) + name + b'\0' + payload


def scope(payload, tag=b'\1'):
    return tag + struct.pack('<I', len(tag) + 4 + len(payload)) + payload


def attrs(payload):
    return b'A' + vendor(scope(payload))


def main():
    for tool in ([DYN], CLANG):
        if not tool or not shutil.which(tool[0]):
            print('SKIP arm-abi-attributes: missing prerequisite ' + str(tool))
            return
    with tempfile.TemporaryDirectory(prefix='dyn-arm-abi-') as tmp:
        work = Path(tmp)
        source = work / 'src'
        source.mkdir()
        (source / 'main.dyn').write_text('extern fn identity(x:f32) f32\nfn main() { if identity(1.5) != 1.5 { #panic("ABI") } }\n')
        c = work / 'identity.c'
        c.write_text('float identity(float x) { return x; }\n')
        objects = {}
        for abi in ('hard', 'soft'):
            obj = work / (abi + '.o')
            subprocess.run([*CLANG, '--target=arm-none-eabi', '-mcpu=cortex-m7', '-mthumb',
                            '-mfpu=fpv5-d16', '-mfloat-abi=' + abi, '-O2', '-c', str(c),
                            '-o', str(obj)], check=True, timeout=60)
            data = bytearray(obj.read_bytes())
            assert struct.unpack_from('<I', data, 36)[0] & 0x600 == 0, 'fixture must exercise unflagged Clang'
            # Bare-metal fixture does not use EHABI. Discard its index and
            # relocations; the identity function itself has no relocations.
            table = sections(data)
            for at, section in table:
                if section[1] == 0x70000001 or (section[1] == 9 and table[section[7]][1][1] == 0x70000001):
                    struct.pack_into('<I', data, at + 20, 0)
                    if section[1] == 9:
                        struct.pack_into('<I', data, at + 4, 1)
            objects[abi] = data

        checks = 0

        def check(label, data, target_abi, error=None):
            nonlocal checks
            obj, image = work / 'input.o', work / 'image.elf'
            obj.write_bytes(data)
            target = 'thumbv7em-none' + ('-soft' if target_abi == 'soft' else '')
            result = subprocess.run([DYN, 'build', str(source), '--target', target,
                                     '--no-cache', '--quiet', '--link', str(obj), '--output', str(image)],
                                    capture_output=True, timeout=120)
            output = (result.stdout + result.stderr).decode(errors='replace')
            assert (result.returncode != 0 if error else result.returncode == 0), (label, output)
            if error:
                assert error in output, (label, output)
            else:
                flags, = struct.unpack_from('<I', image.read_bytes(), 36)
                assert flags & 0x600 == (0x200 if target_abi == 'soft' else 0x400), label
            checks += 1

        def modified(payload, flags=0):
            data = bytearray(objects['soft'])
            struct.pack_into('<I', data, 36, 0x05000000 | flags)
            at, _ = next((at, s) for at, s in sections(data) if s[1] == 0x70000003)
            if payload is None:
                struct.pack_into('<I', data, at + 4, 1)
            else:
                struct.pack_into('<II', data, at + 16, len(data), len(payload))
                data += payload
            return data

        for abi, data in objects.items():
            check('clang matching ' + abi, data, abi)
            check('clang mismatch ' + abi, data, 'soft' if abi == 'hard' else 'hard', 'ABI')
        for abi, flag, value in (('soft', 0x200, 0), ('hard', 0x400, 1)):
            check('flags without attrs', modified(None, flag), abi)
            check('flags agree', modified(attrs(bytes([28, value])), flag), abi)
            check('flags contradict attrs', modified(attrs(bytes([28, 1-value])), flag), abi, 'ABI')
            for payload in (None, b'A' + vendor(b'opaque\xff', b'unknown'), attrs(b'\x1c\3'), attrs(b'\x1c\3\x1c\3')):
                check('unspecified/compatible', modified(payload), abi)
        for abi, flag in (('soft', 0x200), ('hard', 0x400)):
            for flags in (0, flag):
                check('reject toolchain VFP ' + abi + str(flags),
                      modified(attrs(b'\x1c\2'), flags), abi, 'Arm ABI attributes')
            check('compatible with explicit flags', modified(attrs(b'\x1c\3'), flag), abi)
        for tag in (b'\0', b'\x21', b'\x27', b'\x3e', b'\x3f',
                    b'\x80\1', b'\x81\1', b'\x9c\1', b'\xbf\1', b'\x80\2'):
            value = b'text\0' if tag[0] & 1 else b'\0'
            check('unknown mandatory ' + tag.hex(), modified(attrs(tag + value)),
                  'soft', 'Arm ABI attributes')
        for value in (1, 2):
            for flags in (0, 0x200):
                check('required vendor ' + str(value),
                      modified(attrs(b'\x20' + bytes([value]) + b'vendor\0'), flags),
                      'soft', 'Arm ABI attributes')
        standard = bytes(v for tag in (*range(6, 32), 34, 36, 38, 42, 44, 46, 48, 50, 52)
                         for v in (tag, 0))
        check('recognized standard mandatory metadata', modified(attrs(standard)), 'soft')
        check('default base', modified(attrs(b'')), 'soft')
        check('default base mismatch', modified(attrs(b'')), 'hard', 'ABI')
        check('skip strings and unrelated tags', modified(attrs(b'\4cpu\0\5name\0\x20\0\0\x41\6\x0b\0\xc0\1\7\xc1\1text\0\x1c\1')), 'hard')
        check('skip private/symbol/section data', modified(b'A' + vendor(b'\xff', b'other') + vendor(scope(b'\xff', b'\2') + scope(b'\xff', b'\3') + scope(b'\x1c\1'))), 'hard')
        check('multiple file scopes', modified(b'A' + vendor(scope(b'\6\x0d') + scope(b'\x1c\1'))), 'hard')
        check('duplicate same', modified(attrs(b'\x1c\1\x1c\1')), 'hard')
        bad = [b'', b'B', b'A\1', b'A' + struct.pack('<I', 4),
               b'A' + struct.pack('<I', 100) + b'aeabi\0',
               b'A' + struct.pack('<I', 9) + b'aeabi',
               b'A' + vendor(b'\1\5'), b'A' + vendor(b'\1' + struct.pack('<I', 4)),
               b'A' + vendor(b'\1' + struct.pack('<I', 100)),
               attrs(b'\x80'), attrs(b'\x80' * 5 + b'\0'), attrs(b'\x1c\x80'),
               attrs(b'\x1c\xff\xff\xff\xff\x10'), attrs(b'\4unterminated'),
               attrs(b'\x20\1unterminated'), attrs(b'\x1c\4'), attrs(b'\x1c\0\x1c\1')]
        # Every nonempty truncation of a valid attribute section must fail.
        valid = attrs(b'\x1c\1')
        bad += [valid[:n] for n in range(2, len(valid))]
        for i, payload in enumerate(bad):
            check('malformed ' + str(i), modified(payload), 'soft', 'malformed Arm ABI attributes')
        print(f'PASS arm-abi-attributes: {checks} real Clang, flag, compatibility and malformed cases')


if __name__ == '__main__':
    main()
