#!/usr/bin/env python3
"""Fail-closed RISC-V runtime immediates, with Clang as an optional byte oracle."""
import importlib.util
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_runtime_immediates', ROOT / 'tools/native-runtime.py')
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
spec.loader.exec_module(runtime)


def assembled(target, instruction):
    assembler = runtime.Assembler(target)
    assembler.line(instruction)
    return bytes(assembler.sections['.text'].data)


def rejected(target, instruction, message):
    try:
        assembled(target, instruction)
    except ValueError as error:
        assert message in str(error), (target, instruction, str(error))
    else:
        raise AssertionError(('invalid immediate accepted', target, instruction))


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def elf_text(data):
    # Read only the ELF section metadata needed to locate Clang's .text bytes.
    if data[4] == 1:
        offset = struct.unpack_from('<I', data, 32)[0]
        stride, count, strings = struct.unpack_from('<HHH', data, 46)
        sections = [struct.unpack_from('<IIIIIIIIII', data, offset + i * stride) for i in range(count)]
    else:
        offset = struct.unpack_from('<Q', data, 40)[0]
        stride, count, strings = struct.unpack_from('<HHH', data, 58)
        sections = [struct.unpack_from('<IIQQQQIIQQ', data, offset + i * stride) for i in range(count)]
    names = data[sections[strings][4]:sections[strings][4] + sections[strings][5]]
    for section in sections:
        start = section[0]
        if names[start:names.index(0, start)] == b'.text':
            return data[section[4]:section[4] + section[5]]
    raise AssertionError('Clang ELF object has no .text')


valid = {}
for bits in (32, 64):
    target = f'riscv{bits}-none'
    cases = []
    spellings = [(-2048, '-2048'), (-1, '-1'), (0, '0'), (2047, '2047'),
                 (-2048, hex((1 << bits) - 2048)), (-1, hex((1 << bits) - 1))]
    if bits == 32:
        spellings += [(-2048, hex((1 << 64) - 2048)), (-1, hex((1 << 64) - 1))]
    for op in ('addi', 'andi', 'xori', 'sltiu'):
        for expected, spelling in spellings:
            instruction = f'{op} a0, a1, {spelling}'
            data = assembled(target, instruction)
            word, = struct.unpack('<I', data)
            assert signed(word >> 20, 12) == expected, (target, instruction)
            cases.append(instruction)
        for value in (-2049, 2048, 4095, (1 << bits) - 2049, 1 << bits):
            rejected(target, f'{op} a0, a1, {value}', 'signed 12-bit')
        if bits == 64:
            rejected(target, f'{op} a0, a1, 0xffffffff', 'signed 12-bit')
    for op in ('slli', 'srli', 'srai'):
        for amount in (0, bits - 1):
            instruction = f'{op} a0, a1, {amount}'
            word, = struct.unpack('<I', assembled(target, instruction))
            assert (word >> 20) & (bits - 1) == amount
            assert word >> 26 == (16 if op == 'srai' else 0)
            cases.append(instruction)
        for amount in (-1, bits, 4096):
            rejected(target, f'{op} a0, a1, {amount}', 'shift amount')
    for value in (0, 0x80000, 0xfffff):
        instruction = f'lui a0, {value}'
        word, = struct.unpack('<I', assembled(target, instruction))
        assert word >> 12 == value
        cases.append(instruction)
    for value in (-1, 1 << 20):
        rejected(target, f'lui a0, {value}', 'unsigned 20-bit')
    for op in ('lw', 'lbu', 'sw', 'sb', 'fld', 'fsd', 'flw', 'fsw') + (('ld', 'lwu', 'sd') if bits == 64 else ()):
        register = 'f0' if op.startswith('f') else 'a0'
        store = op in ('sw', 'sb', 'sd', 'fsd', 'fsw')
        for expected, spelling in spellings:
            # This dialect's memory operand parser accepts decimal offsets.
            value = int(spelling, 0)
            instruction = f'{op} {register}, {value}(a1)'
            word, = struct.unpack('<I', assembled(target, instruction))
            immediate = ((word >> 25) << 5 | (word >> 7) & 31) if store else word >> 20
            assert signed(immediate, 12) == expected, (target, instruction)
            cases.append(instruction)
        for value in (-2049, 2048, 4095):
            rejected(target, f'{op} {register}, {value}(a1)', 'signed 12-bit')
    # The li pseudo-instruction still accepts whole-register unsigned patterns.
    literals = [0, 1, -1, 2048, -2049, 0x80000000, 0x88000000, 0xffffffff]
    if bits == 64:
        literals += [0x8000000000000000, 0xffffffffffffffff, 0x123456789abcdef0]
    for value in literals:
        registers = [0] * 32
        code = assembled(target, f'li a0, {value}')
        for at in range(0, len(code), 4):
            word, = struct.unpack_from('<I', code, at)
            opcode, rd, rs = word & 127, (word >> 7) & 31, (word >> 15) & 31
            if opcode == 0x37:
                result = signed(word & 0xfffff000, 32)
            else:
                assert opcode == 0x13
                if (word >> 12) & 7 == 1:
                    result = registers[rs] << ((word >> 20) & (bits - 1))
                else:
                    assert (word >> 12) & 7 == 0
                    result = registers[rs] + signed(word >> 20, 12)
            registers[rd] = result & ((1 << bits) - 1)
        assert registers[10] == value & ((1 << bits) - 1), (target, value)
    valid[target] = cases

with tempfile.TemporaryDirectory(prefix='dyn-runtime-immediates-') as directory:
    work = Path(directory)
    for bits in (32, 64):
        target = f'riscv{bits}-none'
        for displacement, forward, accepted in ((4094, True, True), (4096, True, False),
                                                 (-4096, False, True), (-4098, False, False),
                                                 (5, True, False)):
            padding = displacement - 4 if forward else -displacement
            padding_source = '.byte ' + ','.join(['0'] * padding) + '\n'
            text = ('.text\nbeq a0, a1, target\n' + padding_source + 'target:\n' if forward
                    else '.text\ntarget:\n' + padding_source + 'beq a0, a1, target\n')
            source = work / 'branch.S'
            source.write_text(text)
            try:
                assembler = runtime.Assembler(target).assemble(source)
            except ValueError as error:
                assert not accepted and 'RISC-V branch range' in str(error), (target, text, error)
            else:
                assert accepted, (target, text)
    clang = shlex.split(os.environ.get('CLANG', 'clang'))
    if shutil.which(clang[0]):
        for target, cases in valid.items():
            bits = 32 if '32' in target else 64
            output = work / f'oracle-{bits}.o'
            command = [*clang, '--target=' + ('riscv32' if bits == 32 else 'riscv64'),
                       '-march=' + ('rv32imafd' if bits == 32 else 'rv64imafd'),
                       '-mabi=' + ('ilp32d' if bits == 32 else 'lp64d'),
                       '-mno-relax', '-c', '-x', 'assembler', '-o', str(output), '-']
            subprocess.run(command, input='.text\n' + '\n'.join(cases) + '\n', text=True, capture_output=True, check=True, timeout=60)
            expected = elf_text(output.read_bytes())
            actual = b''.join(assembled(target, instruction) for instruction in cases)
            assert actual == expected, ('Clang encoding mismatch', target)
        print('PASS runtime immediates: Clang RV32/RV64 encoding oracle')
    else:
        print('SKIP optional runtime immediate Clang oracle: compiler unavailable')
print('PASS runtime immediates: signed I/S endpoints, canonical bit patterns, shifts, LUI, li semantics and branch guards')
