#!/usr/bin/env python3
"""Validate flash/RAM layout and optionally execute startup with Unicorn.

Unicorn models the CPU and mapped memory, not STM32 peripherals. Hardware
qualification is separate. Install unicorn in a disposable environment to
exercise the execution checks, e.g. uv run --with unicorn python this-file.
"""
import os
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
TARGET = 'thumbv7em-none-nucleo-h753zi'
try:
    import unicorn as uc
    from unicorn import arm_const as arm
except ImportError:
    uc = None


def inspect(image):
    data = image.read_bytes()
    assert data[:6] == b'\x7fELF\x01\x01'
    assert struct.unpack_from('<HH', data, 16) == (2, 40)
    entry, phoff, shoff = struct.unpack_from('<III', data, 24)
    phsize, phcount, shsize, shcount = struct.unpack_from('<HHHH', data, 42)
    loads = [struct.unpack_from('<IIIIIIII', data, phoff + i * phsize)
             for i in range(phcount) if struct.unpack_from('<I', data, phoff + i * phsize)[0] == 1]
    assert len(loads) == 3
    for _, offset, address, physical, filesz, memsz, flags, alignment in loads:
        assert 0x08000000 <= physical and physical + filesz <= 0x08200000
        assert filesz <= memsz and offset + filesz <= len(data)
        assert address % alignment == offset % alignment
        if flags & 2:
            assert address == 0x24000000 and address + memsz <= 0x24080000
            assert physical != address
        else:
            assert physical == address
    vectors = loads[0][1]
    sp, reset = struct.unpack_from('<II', data, vectors)
    assert sp == 0x20020000 and reset == entry and entry & 1
    assert all(struct.unpack_from('<I', data, vectors + i * 4)[0] & 1 for i in range(16, 166))
    sections = [struct.unpack_from('<IIIIIIIIII', data, shoff + i * shsize) for i in range(shcount)]
    symbols = {}
    for section in sections:
        if section[1] != 2:
            continue
        strings = sections[section[6]]
        names = data[strings[4]:strings[4] + strings[5]]
        for offset in range(section[4], section[4] + section[5], section[9]):
            name, value, _, _, _, _ = struct.unpack_from('<IIIBBH', data, offset)
            end = names.find(b'\0', name)
            symbols[names[name:end].decode()] = value
    writable = loads[-1]
    assert symbols['__data_load'] == writable[3]
    assert symbols['__data_start'] == writable[2]
    assert symbols['_edata'] == writable[2] + writable[4]
    assert symbols['_end'] == writable[2] + writable[5]
    return data, loads, symbols, sp, entry


def execute(data, loads, symbols, sp, entry):
    machine = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB | uc.UC_MODE_MCLASS)
    machine.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_M7)
    for address, size in ((0x08000000, 0x200000), (0x24000000, 0x80000),
                          (0x20000000, 0x20000), (0x58020000, 0x10000),
                          (0x40004000, 0x1000), (0xe000e000, 0x1000)):
        machine.mem_map(address, size)
    # Deliberately dirty RAM proves startup copies data and clears BSS.
    machine.mem_write(0x24000000, b'\xa5' * 0x80000)
    for _, offset, _, physical, filesz, _, _, _ in loads:
        machine.mem_write(physical, data[offset:offset + filesz])
    machine.mem_write(0x4000481c, struct.pack('<I', 0x80))  # UART TX ready
    machine.mem_write(0x5802480c, struct.pack('<I', 4))  # reset SCUEN
    supply_reads = []
    output = bytearray()
    status = []

    def write(cpu, access, address, size, value, context):
        if 0x24000000 <= address < 0x24080000 or 0x20000000 <= address < 0x20020000:
            assert len(supply_reads) >= 3, 'RAM write before supply ready'
        if address == 0x40004828:
            def reg(at):
                return struct.unpack('<I', cpu.mem_read(at, 4))[0]
            assert reg(0x580244e0) & 8, 'GPIOD clock disabled'
            assert reg(0x580244e8) & 0x40000, 'USART3 clock disabled'
            assert reg(0x58024454) & 7 == 3, 'USART3 clock is not HSI'
            assert (reg(0x58020c00) >> 16) & 3 == 2, 'PD8 is not alternate function'
            assert reg(0x58020c24) & 15 == 7, 'PD8 is not AF7'
            output.append(value & 255)

    def read(cpu, access, address, size, value, context):
        if address == 0x58024804:
            assert struct.unpack('<I', cpu.mem_read(0x5802480c, 4))[0] & 7 == 2
            supply_reads.append(True)
            if len(supply_reads) == 3:
                cpu.mem_write(address, struct.pack('<I', 0x2000))

    def code(cpu, address, size, context):
        if address == symbols['main'] & ~1:
            start, end = symbols['__bss_start'], symbols['_end']
            assert bytes(cpu.mem_read(start, end - start)) == bytes(end - start)
            start, end = symbols['__data_start'], symbols['_edata']
            assert cpu.mem_read(start, end - start) == cpu.mem_read(symbols['__data_load'], end - start)
        if address == symbols['dyn_exit'] & ~1:
            status.append(cpu.reg_read(arm.UC_ARM_REG_R0))
            cpu.emu_stop()

    machine.hook_add(uc.UC_HOOK_MEM_READ, read)
    machine.hook_add(uc.UC_HOOK_MEM_WRITE, write)
    machine.hook_add(uc.UC_HOOK_CODE, code)
    machine.reg_write(arm.UC_ARM_REG_SP, sp)
    machine.emu_start(entry, 0, count=20_000_000)
    assert status == [0], (status, output)
    assert output == b'hello from NUCLEO-H753ZI\n', output
    assert struct.unpack('<I', machine.mem_read(0xe000ed08, 4))[0] == 0x08000000
    assert struct.unpack('<I', machine.mem_read(0x4000480c, 4))[0] == 556
    assert struct.unpack('<I', machine.mem_read(0x40004800, 4))[0] == 9


with tempfile.TemporaryDirectory(prefix='dyn-nucleo-') as directory:
    root = Path(directory)
    for release in (False, True):
        image = root / 'firmware.elf'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/nucleo'), '--target', TARGET,
                        '--no-cache', '--quiet', '--output', str(image)] + (['--release'] if release else []),
                       check=True, timeout=120)
        details = inspect(image)
        if uc:
            execute(*details)
    rejected = subprocess.run([DYN, 'build', str(ROOT / 'tests/nucleo'), '--target', TARGET,
                               '--no-cache', '--quiet', '--output', str(root / 'external.elf')],
                              env={**os.environ, 'DYN_LINKER': 'external'}, capture_output=True, text=True, timeout=120)
    assert rejected.returncode != 0 and 'requires the built-in linker' in rejected.stderr, rejected.stderr
    overflow = root / 'overflow' 
    overflow.mkdir()
    (overflow / 'main.dyn').write_text('pub storage: [600000]u8\nfn main() { storage[0] = 1 }\n')
    result = subprocess.run([DYN, 'build', str(overflow), '--target', TARGET, '--no-cache', '--quiet',
                             '--output', str(root / 'overflow.elf')], capture_output=True, text=True, timeout=120)
    assert result.returncode != 0 and 'exceeds RAM region' in result.stderr, result.stderr
    (overflow / 'main.dyn').write_text('use "std/io"\nfn main() { _ = io.write_all(io.stdout(), "' + 'x' * 2200000 + '") }\n')
    result = subprocess.run([DYN, 'build', str(overflow), '--target', TARGET, '--no-cache', '--quiet',
                             '--output', str(root / 'overflow.elf')], capture_output=True, text=True, timeout=120)
    assert result.returncode != 0 and 'exceeds ROM region' in result.stderr, result.stderr
print('PASS NUCLEO-H753ZI flash/RAM layout, vectors, initialization symbols, ROM/RAM overflow rejection (debug/release)')
print('PASS Unicorn startup, dirty RAM initialization, arena and UART writes' if uc else
      'SKIP CPU execution: optional unicorn module unavailable')
print('Hardware execution remains unverified')
