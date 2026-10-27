#!/usr/bin/env python3
"""MMIO helper semantics on host memory, and privileged helper cross-links."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE='''use "std/embedded/uart" uart
use "std/embedded/timer" timer
use "std/errors" errors
fn check(ok: bool) { if !ok { #panic("embedded helper") } }
fn main() {
  registers: [8]u32 = []
  address := #cast(usize, &registers[0])
  device := uart.Uart{ data: address, status: address + 4, ready_mask: 4, ready_when_set: true, width: uart.RegisterWidth.Word }
  check(!uart.ready(&device))
  registers[1] = 4
  uart.write(&device, "ABC")
  check(registers[0] == 67)
  device.ready_when_set = false
  check(!uart.ready(&device))
  registers[1] = 0
  uart.write_byte(&device, 88)
  check(registers[0] == 88)
  tick := timer.SysTick{ base: address }
  check(!timer.start(&tick, 0, true, true).ok && registers[0] == 88)
  check(!timer.start(&tick, 1, true, true).ok && registers[0] == 88)
  check(timer.start(&tick, 2, false, false).ok && registers[1] == 1)
  check(timer.start(&tick, 100, true, true).ok)
  check(registers[0] == 7 && registers[1] == 99 && registers[2] == 0)
  registers[2] = 0xff123456
  check(timer.current(&tick) == 0x123456)
  registers[0] |= 0x10000
  check(timer.elapsed(&tick))
  timer.stop(&tick)
  check(registers[0] == 0)
  check(timer.start(&tick, 16777216, false, false).ok && registers[1] == 0xffffff)
  check(timer.start(&tick, 16777217, false, false).kind == errors.Kind.InvalidInput)
  clock := timer.MachineTimer{ time: address, compare: address + 8 }
  registers[0] = 0x89abcdef
  registers[1] = 0x12345678
  check(timer.now(&clock) == 0x1234567889abcdef)
  timer.deadline(&clock, 0xfedcba9876543210)
  check(registers[2] == 0x76543210 && registers[3] == 0xfedcba98)
  timer.disarm(&clock)
  check(registers[2] == 0xffffffff && registers[3] == 0xffffffff)
}
'''
PRIVILEGED='''use "std/embedded/interrupt" irq
fn main() {
  a := irq.disable()
  b := irq.disable()
  irq.restore(b)
  irq.restore(a)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-embedded-') as directory:
    work=Path(directory);(work/'main.dyn').write_text(SOURCE)
    for mode in ('--debug','--release'):
        output=work/'program'
        subprocess.run([DYN,'build',str(work),mode,'--quiet','--no-cache','--output',str(output)],check=True,timeout=300)
        subprocess.run([str(output)],check=True,timeout=30)
    (work/'main.dyn').write_text(PRIVILEGED)
    for target in ('riscv64-none','riscv32-none','riscv32-none-soft','thumbv7em-none','thumbv7em-none-soft','thumbv7em-none-nucleo-h753zi'):
        for mode in ('--debug','--release'):
            subprocess.run([DYN,'build',str(work),'--target',target,mode,'--quiet','--output',str(work/target)],check=True,timeout=300)
print('PASS embedded UART/timer MMIO semantics, period validation, 64-bit split access and privileged interrupt cross-links')
