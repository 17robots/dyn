#!/usr/bin/env python3
"""Emit the freestanding Dyn Wasm runtime without a C compiler or LLVM.

Objects use the WebAssembly linking v2 ABI and standard code relocations.
"""
import argparse
import struct
from pathlib import Path

I32, I64 = 0x7f, 0x7e


def uleb(value):
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    return bytes(out + bytes([value]))


def sleb(value):
    out = bytearray()
    while True:
        byte = value & 127
        value >>= 7
        done = (value == 0 and not byte & 64) or (value == -1 and byte & 64)
        out.append(byte if done else byte | 128)
        if done:
            return bytes(out)


def string(value):
    data = value.encode()
    return uleb(len(data)) + data


def vector(items):
    return uleb(len(items)) + b''.join(items)


def section(kind, data):
    return bytes([kind]) + uleb(len(data)) + data


def custom(name, data):
    return section(0, string(name) + data)


def local(index):
    return b'\x20' + uleb(index)


def setlocal(index):
    return b'\x21' + uleb(index)


def const(value):
    return b'\x41' + sleb(value)


def const64(value):
    return b'\x42' + sleb(value)


class Object:
    def __init__(self):
        self.types = []
        self.imports = []
        self.functions = []
        self.stack = False
        self.exports = []

    def signature(self, params, results):
        sig = (tuple(params), tuple(results))
        if sig not in self.types:
            self.types.append(sig)
        return self.types.index(sig)

    def imported(self, name, params, results, module='env', field=None):
        self.imports.append((name, module, field or name, self.signature(params, results)))

    def function(self, name, params, results, body, locals=()):
        self.functions.append((name, self.signature(params, results), body, locals))

    def write(self, path):
        names = [item[0] for item in self.imports + self.functions]
        imports = [string(module) + string(field) + b'\0' + uleb(sig)
                   for name, module, field, sig in self.imports]
        imports.append(string('env') + string('__linear_memory') + b'\x02\x00\x00')
        if self.stack:
            imports.append(string('env') + string('__stack_pointer') + b'\x03\x7f\x01')
        symbols = [b'\x00' + uleb(0x50) + uleb(i) + string(name)
                   for i, (name, *_) in enumerate(self.imports)]
        symbols += [b'\x00' + uleb(0x20 if name in self.exports else 0) + uleb(len(self.imports) + i) + string(name)
                    for i, (name, *_) in enumerate(self.functions)]
        if self.stack:
            symbols.append(b'\x02\x10\x00')
        code = bytearray(uleb(len(self.functions)))
        relocs = []
        for name, sig, pieces, locals in self.functions:
            body = bytearray(vector([uleb(1) + bytes([kind]) for kind in locals]))
            pending = []
            for piece in pieces:
                if isinstance(piece, tuple):
                    kind, target = piece
                    body.append(0x10 if kind == 'call' else (0x23 if kind == 'get' else 0x24))
                    index = names.index(target) if kind == 'call' else len(names)
                    pending.append((0 if kind == 'call' else 7, len(body), index))
                    body.extend(b'\x80\x80\x80\x80\x00')
                else:
                    body.extend(piece)
            body.append(0x0b)
            size = uleb(len(body))
            for kind, offset, index in pending:
                relocs.append(uleb(kind) + uleb(len(code) + len(size) + offset) + uleb(index))
            code.extend(size + body)
        data = b'\0asm\x01\0\0\0'
        data += section(1, vector([b'\x60' + vector([bytes([p]) for p in ps]) + vector([bytes([r]) for r in rs]) for ps, rs in self.types]))
        data += section(2, vector(imports))
        data += section(3, vector([uleb(f[1]) for f in self.functions]))
        if self.exports:
            data += section(7, vector([string(name) + b'\x00' + uleb(names.index(name)) for name in self.exports]))
        data += section(10, bytes(code))
        symtab = vector(symbols)
        data += custom('linking', b'\x02\x08' + uleb(len(symtab)) + symtab)
        if relocs:
            data += custom('reloc.CODE', uleb(4 if self.exports else 3) + vector(relocs))
        Path(path).write_bytes(data)


def floating_remainder(obj, wide):
    """Exact binary long division; subtraction obeys Sterbenz's lemma.

    Scaling by powers of two preserves the divisor exactly. Unlike a truncated
    quotient, this handles huge ratios without overflow or loss of low bits.
    """
    kind = 0x7c if wide else 0x7d
    opcode = lambda single, double: bytes([double if wide else single])
    number = lambda value: opcode(0x43, 0x44) + struct.pack('<d' if wide else '<f', value)
    absolute = opcode(0x8b, 0x99)
    equal, unequal = opcode(0x5b, 0x61), opcode(0x5c, 0x62)
    greater, greater_equal = opcode(0x5e, 0x64), opcode(0x60, 0x66)
    add, subtract, multiply = opcode(0x92, 0xa0), opcode(0x93, 0xa1), opcode(0x94, 0xa2)
    copy_sign = opcode(0x98, 0xa6)
    # Locals 2/3 hold magnitudes, 4 the scaled divisor, 5 its doubled value.
    body = [local(0), absolute, setlocal(2), local(1), absolute, setlocal(3),
            local(2), local(2), subtract, number(0), unequal,
            local(3), local(3), unequal, b'\x72',
            local(3), number(0), equal, b'\x72\x04\x40',
            number(float('nan')), b'\x0f\x0b',
            local(3), number(float('inf')), equal, b'\x04\x40', local(0), b'\x0f\x0b',
            local(3), setlocal(4), b'\x02\x40\x03\x40',
            local(4), local(4), add, setlocal(5),
            local(5), local(2), greater, b'\x0d\x01',
            local(5), setlocal(4), b'\x0c\x00\x0b\x0b',
            b'\x02\x40\x03\x40', local(2), local(4), greater_equal,
            b'\x04\x40', local(2), local(4), subtract, setlocal(2), b'\x0b',
            local(4), local(3), equal, b'\x0d\x01',
            local(4), number(0.5), multiply, setlocal(4), b'\x0c\x00\x0b\x0b',
            local(2), local(0), copy_sign]
    obj.function('fmod' if wide else 'fmodf', [kind, kind], [kind], body, [kind]*4)


def browser():
    obj = Object()
    floating_remainder(obj, False)
    floating_remainder(obj, True)
    # Byte loops preserve MVP compatibility (no bulk-memory feature required).
    for name in ('memcpy', 'memset'):
        load = local(1) if name == 'memset' else local(1) + local(3) + b'\x6a\x2d\x00\x00'
        body = [const(0), setlocal(3), b'\x02\x40\x03\x40', local(3), local(2), b'\x4f\x0d\x01', local(0), local(3), b'\x6a', load, b'\x3a\x00\x00', local(3), const(1), b'\x6a', setlocal(3), b'\x0c\x00\x0b\x0b', local(0)]
        obj.function(name, [I32]*3, [I32], body, [I32])
    obj.function('memmove', [I32]*3, [I32], [local(0), local(1), b'\x49\x04\x7f', local(0), local(1), local(2), ('call', 'memcpy'), b'\x05\x02\x40\x03\x40', local(2), b'\x45\x0d\x01', local(2), const(1), b'\x6b', setlocal(2), local(0), local(2), b'\x6a', local(1), local(2), b'\x6a\x2d\x00\x00\x3a\x00\x00\x0c\x00\x0b\x0b', local(0), b'\x0b'])
    obj.function('dyn_panic', [I32]*2, [], [b'\x00'])
    obj.function('dyn_wasm_grow_pages', [I32], [I32], [local(0), b'\x40\x00'])
    # Compiler-rt ABI: sret pointer followed by low/high halves of operands.
    # Store low product; calculate high half from four 32-bit products.
    mask = const64(0xffffffff)
    lo = lambda n: local(n) + mask + b'\x83'
    hi = lambda n: local(n) + const64(32) + b'\x88'
    body = [lo(1), lo(3), b'\x7e', setlocal(5), lo(1), hi(3), b'\x7e', setlocal(6), hi(1), lo(3), b'\x7e', setlocal(7), hi(5), lo(6), b'\x7c', lo(7), b'\x7c', setlocal(8), local(0), local(1), local(3), b'\x7e\x37\x03\x00', local(0), hi(1), hi(3), b'\x7e', hi(6), b'\x7c', hi(7), b'\x7c', hi(8), b'\x7c', local(2), local(3), b'\x7e\x7c', local(1), local(4), b'\x7e\x7c\x37\x03\x08']
    obj.function('__multi3', [I32, I64, I64, I64, I64], [], body, [I64]*4)
    return obj


def wasi():
    obj = Object()
    obj.stack = True
    specs = [('fd_write', [I32]*4), ('fd_read', [I32]*4), ('fd_close', [I32]), ('args_sizes_get', [I32]*2), ('args_get', [I32]*2), ('path_open', [I32]*5 + [I64]*2 + [I32]*2), ('random_get', [I32]*2), ('clock_time_get', [I32, I64, I32])]
    for name, params in specs:
        obj.imported('wasi_' + name, params, [I32], 'wasi_snapshot_preview1', name)
    for suffix in ('write', 'read'):
        obj.function('dyn_wasi_' + suffix, [I32]*4, [I32], [('get', '__stack_pointer'), const(16), b'\x6b', setlocal(4), local(4), ('set', '__stack_pointer'), local(4), local(1), b'\x36\x02\x00', local(4), local(2), b'\x36\x02\x04', local(0), local(4), const(1), local(3), ('call', 'wasi_fd_' + suffix), setlocal(5), local(4), const(16), b'\x6a', ('set', '__stack_pointer'), local(5)], [I32]*2)
    for suffix, target, params in [('close', 'fd_close', [I32]), ('args_sizes', 'args_sizes_get', [I32]*2), ('args', 'args_get', [I32]*2), ('random', 'random_get', [I32]*2), ('clock', 'clock_time_get', [I32,I64,I32]), ('time_clock', 'clock_time_get', [I32,I64,I32])]:
        name = 'dyn_time_wasi_clock' if suffix == 'time_clock' else 'dyn_wasi_' + suffix
        obj.function(name, params, [I32], [*[local(i) for i in range(len(params))], ('call', 'wasi_' + target)])
    obj.function('dyn_wasi_open_read', [I32]*4, [I32], [local(0), const(0), local(1), local(2), const(0), const64(2), const64(0), const(0), local(3), ('call', 'wasi_path_open')])
    return obj


def start():
    obj = Object()
    obj.imported('__original_main', [], [I32])
    obj.imported('wasi_proc_exit', [I32], [], 'wasi_snapshot_preview1', 'proc_exit')
    obj.function('_start', [], [], [('call', '__original_main'), ('call', 'wasi_proc_exit'), b'\x00'])
    obj.exports.append('_start')
    return obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    outputs = parser.add_mutually_exclusive_group(required=True)
    outputs.add_argument('--output-dir', type=Path)
    outputs.add_argument('--output', type=Path)
    args = parser.parse_args()
    directory = args.output_dir or args.output.parent
    directory.mkdir(parents=True, exist_ok=True)
    valid_names = ('dynrt_wasm.o', 'dynrt_wasi_support.o', 'dynrt_wasi_start.o')
    if args.output and args.output.name not in valid_names:
        parser.error('--output filename must be one of ' + ', '.join(valid_names))
    for name, obj in [('dynrt_wasm.o', browser()), ('dynrt_wasi_support.o', wasi()), ('dynrt_wasi_start.o', start())]:
        if args.output is None or args.output.name == name:
            obj.write(directory / name)


if __name__ == '__main__':
    main()
