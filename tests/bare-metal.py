#!/usr/bin/env python3
"""riscv64-none and riscv32-none (QEMU virt board) and thumbv7em-none (QEMU
mps2-an500, Cortex-M7): static images, run when QEMU is available.

Set DYN_QEMU_RISCV64, DYN_QEMU_RISCV32 or DYN_QEMU_ARM to a command that runs
qemu-system-riscv64, qemu-system-riscv32 or qemu-system-arm, for example a
container wrapper; otherwise the QEMU from PATH is used if present.
A wrapper must stop the guest itself when killed, or bound it with its own
timeout: killing a `podman run` client leaves the container running, e.g.
DYN_QEMU_RISCV64="podman run --rm --init -v $TMPDIR:$TMPDIR dyn-qemu timeout 50 qemu-system-riscv64".
"""
import os
from pathlib import Path
import shlex
import shutil
import signal
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
PANIC = '''use "std/io"

fn pick(values: []const u8, index: usize) u8 {
  return values[index]
}

fn main() {
  defer cleanup()
  values: [3]u8 = [1, 2, 3]
  _ = io.write_all(io.stdout(), "before\\n")
  _ = pick(values[..], 5)
}

fn cleanup() {
  _ = io.write_all(io.stdout(), "cleanup ran\\n")
}
'''


def check_image(path, bits, machine, low, high):
    data = path.read_bytes()
    assert data[:4] == b'\x7fELF' and data[4] == (2 if bits == 64 else 1), path
    kind, found = struct.unpack_from('<HH', data, 16)
    if bits == 64:
        entry, phoff = struct.unpack_from('<QQ', data, 24)
        count, = struct.unpack_from('<H', data, 56)
    else:
        entry, phoff = struct.unpack_from('<II', data, 24)
        count, = struct.unpack_from('<H', data, 44)
    assert (kind, found) == (2, machine), (kind, found)
    # RISC-V starts at the image base; Cortex-M from its vector table, and
    # the entry symbol is Thumb code.
    assert entry == low if machine == 243 else entry & 1 and low <= entry < high, hex(entry)
    for index in range(count):
        if bits == 64:
            kind, _, _, address, _, _, memory_size, _ = struct.unpack_from('<IIQQQQQQ', data, phoff + 56 * index)
        else:
            kind, _, address, _, _, memory_size, _, _ = struct.unpack_from('<IIIIIIII', data, phoff + 32 * index)
        assert kind not in (2, 3), 'bare-metal image must not be dynamic'
        if kind == 1:
            assert low <= address and address + memory_size <= high, hex(address)



def check_rv64_memory_start(path):
    """Evaluate the linked leaf independently; backing must start after ELF BSS.

    This catches truncated immediates even when image layout hides corruption.
    Only the small integer instruction subset used by this leaf is accepted.
    """
    data = path.read_bytes()
    shoff, = struct.unpack_from('<Q', data, 40)
    shsize, shcount = struct.unpack_from('<HH', data, 58)
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, shoff + i * shsize)
                for i in range(shcount)]
    symbols = {}
    for section in sections:
        if section[1] != 2:  # SHT_SYMTAB
            continue
        strings = sections[section[6]]
        names = data[strings[4]:strings[4] + strings[5]]
        for at in range(section[4], section[4] + section[5], section[9]):
            name, _, _, index, value, _ = struct.unpack_from('<IBBHQQ', data, at)
            symbols[names[name:names.index(b'\0', name)].decode()] = (index, value)
    index, pc = symbols['dyn_memory_start']
    section = sections[index]
    end = symbols['_end'][1]
    registers = [0] * 32
    mask = (1 << 64) - 1
    def signed(value, bits):
        return value - (1 << bits) if value & (1 << (bits - 1)) else value
    for _ in range(32):
        offset = section[4] + pc - section[3]
        word, = struct.unpack_from('<I', data, offset)
        op, rd, rs1, rs2 = word & 127, (word >> 7) & 31, (word >> 15) & 31, (word >> 20) & 31
        funct = (word >> 12) & 7
        if word == 0x00008067:  # ret
            assert registers[10] == (end + 4095) & ~4095, (path, hex(end), hex(registers[10]))
            return
        if op == 0x17:  # auipc
            value = pc + signed(word & 0xfffff000, 32)
        elif op == 0x37:  # lui
            value = signed(word & 0xfffff000, 32)
        elif op == 0x13 and funct == 0:  # addi
            value = registers[rs1] + signed(word >> 20, 12)
        elif op == 0x13 and funct == 1:  # slli
            value = registers[rs1] << ((word >> 20) & 63)
        elif op == 0x33 and funct == 0 and word >> 25 == 0:  # add
            value = registers[rs1] + registers[rs2]
        elif op == 0x33 and funct == 7:  # and
            value = registers[rs1] & registers[rs2]
        else:
            raise AssertionError(('unexpected memory-start instruction', hex(pc), hex(word)))
        if rd:
            registers[rd] = value & mask
        pc += 4
    raise AssertionError('memory-start leaf did not return')


def run_guest(command):
    """Run QEMU in its own process group, keep at most 64 KiB of console
    output, and kill the whole group on timeout so no guest outlives the test."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise SystemExit(f'FAIL QEMU guest did not exit within 60 seconds: {command}')
    return subprocess.CompletedProcess(command, process.returncode, output[:65536], b'')


VIRT = ['-machine', 'virt', '-bios', 'none']
MPS2 = ['-machine', 'mps2-an500', '-semihosting-config', 'enable=on,target=native']
# Target, pointer bits, ELF machine, image range, QEMU variable and program, machine options.
TARGETS = (('riscv64-none', 64, 243, 0x80000000, 0x87F00000, 'DYN_QEMU_RISCV64', 'qemu-system-riscv64', VIRT),
           ('riscv32-none', 32, 243, 0x80000000, 0x87F00000, 'DYN_QEMU_RISCV32', 'qemu-system-riscv32', VIRT),
           ('thumbv7em-none', 32, 40, 0, 0x400000, 'DYN_QEMU_ARM', 'qemu-system-arm', MPS2))
ran_targets = []
for target, bits, machine, low, high, variable, program, board in TARGETS:
    qemu = shlex.split(os.environ.get(variable, '')) or ([program] if shutil.which(program) else [])
    with tempfile.TemporaryDirectory(prefix='dyn-bare-metal-') as temporary:
        work = Path(temporary)
        (work / 'panic').mkdir()
        (work / 'panic/main.dyn').write_text(PANIC)
        images = []
        for name, source in (('hello', ROOT / 'tests/bare-metal'), ('panic', work / 'panic')):
            for release in (False, True):
                image = work / f'{name}-{"release" if release else "debug"}'
                subprocess.run([DYN, 'build', str(source), '--target', target, '--no-cache', '--quiet',
                                '--output', str(image)] + (['--release'] if release else []), check=True, timeout=120)
                check_image(image, bits, machine, low, high)
                if target == 'riscv64-none':
                    check_rv64_memory_start(image)
                images.append((name, release, image))
        refused = subprocess.run([DYN, 'run', str(ROOT / 'tests/bare-metal'), '--target', target],
                                 capture_output=True, text=True, timeout=60)
        assert refused.returncode == 2 and 'bare-metal targets build static images only' in refused.stderr, refused
        (work / 'syscall').mkdir()
        (work / 'syscall/main.dyn').write_text('fn main() {\n  _ = #syscall(1, 0)\n}\n')
        rejected = subprocess.run([DYN, 'check', str(work / 'syscall'), '--target', target],
                                  capture_output=True, text=True, timeout=60)
        assert rejected.returncode != 0 and '#syscall requires an operating system' in rejected.stderr, rejected
        (work / 'files').mkdir()
        (work / 'files/main.dyn').write_text('use "std/fs"\n\nfn main() {\n}\n')
        missing = subprocess.run([DYN, 'check', str(work / 'files'), '--target', target],
                                 capture_output=True, text=True, timeout=60)
        assert missing.returncode != 0, missing
        assert missing.stderr.count(f"module 'std/fs' has no source file for target {target}") == 1, missing.stderr
        if not qemu:
            print(f'PASS {target} images (SKIP running: {program} not found)')
            continue
        for name, release, image in images:
            ran = run_guest([*qemu, *board, '-nographic', '-kernel', str(image)])
            output = ran.stdout.replace(b'\r\n', b'\n').decode()
            if name == 'hello':
                assert ran.returncode == 0, (target, ran.returncode, output)
                expected = (f'hello from bare metal\nsum 1498500\nposition 75\nscratch 7\nmmio\n'
                            f'wide 2576981270\nusize {bits}\n')
                assert output == expected, (target, output)
            else:
                assert ran.returncode == 101, (target, ran.returncode, output)
                assert output.startswith('before\ncleanup ran\nruntime check failed (index.ok) in pick\n'), output
                assert ('stack trace:' in output) != release, output
        ran_targets.append(target)
if ran_targets:
    print(f'PASS {", ".join(ran_targets)} on QEMU: console output, arenas, 64-bit arithmetic, '
          'panic cleanup and exit status (debug/release)')
