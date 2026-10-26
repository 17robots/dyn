# Bare metal

The experimental `riscv32-none-soft` target uses the ILP32 integer calling
convention and software binary32/binary64 arithmetic. It runs on the same
QEMU `virt` layout without an FPU:

```sh
dyn build app --target riscv32-none-soft --output app-soft.elf
qemu-system-riscv32 -machine virt -cpu sifive-e31 -bios none -nographic -kernel app-soft.elf
```

Software arithmetic rounds to nearest, ties to even, with gradual underflow.
NaN results are canonical quiet NaNs; floating exception flags are not exposed.
Release builds use SSA where supported; debug builds use the tree emitter.
`tests/rv32-soft.py` checks
debug/release execution, C interoperability, and absence of floating-point
instructions throughout executable sections of the linked image.

`thumbv7em-none-soft` uses the integer AAPCS convention and the same software
arithmetic on QEMU `mps2-an500`. Startup leaves FPU access disabled; internal
64-bit values use core registers and frame storage. Build with
`dyn build app --target thumbv7em-none-soft --output app-soft.elf`, then run:

```sh
qemu-system-arm -machine mps2-an500 -semihosting-config enable=on,target=native -nographic -kernel app-soft.elf
```

Release builds likewise use SSA where supported. `tests/thumb-soft.py` verifies disabled
FPU access, C interoperability, recursive frames, panic cleanup, and a strict
mapping-aware scan for VFP instructions. The linker validates ARM floating
calling conventions from explicit ELF flags and AEABI file attributes.

`--target riscv64-none`, `--target riscv32-none` and `--target thumbv7em-none`
build a static image that runs with no operating system. All three targets
are experimental. The default profiles support one emulated board each. The RISC-V targets run on the
QEMU `virt` machine (RV64GC or RV32GC), entered in machine mode on one hart.
`thumbv7em-none` runs on the QEMU `mps2-an500` board, a Cortex-M7 with a
double-precision FPU:

```sh
dyn build app --target riscv64-none --output app.elf
qemu-system-riscv64 -machine virt -bios none -nographic -kernel app.elf

dyn build app --target riscv32-none --output app32.elf
qemu-system-riscv32 -machine virt -bios none -nographic -kernel app32.elf

dyn build app --target thumbv7em-none --output app-m7.elf
qemu-system-arm -machine mps2-an500 -semihosting-config enable=on,target=native \
  -nographic -kernel app-m7.elf
```

On `riscv32-none`, pointers and `usize` are 32 bits and the image is an ELF32
file. `u64`, `i64` and `f64` keep their full width: 64-bit integers live in
register pairs, so their arithmetic costs a few instructions more than 32-bit
arithmetic, and 64-bit division and checked multiplication call runtime
helpers. Calls follow the ILP32D convention.

`thumbv7em-none` uses the same 32-bit model with Thumb-2 instructions and the
AAPCS calling convention with floating-point registers (`eabihf`). The core
has too few registers to hold every 64-bit value in a register pair, so some
high words live in floating-point registers and cost one extra move each.

`dyn run` refuses bare-metal targets: run the image under QEMU or load it on
the board.

## What the runtime provides

| Need | RISC-V (`virt`) | Cortex-M7 (`mps2-an500`) |
| --- | --- | --- |
| Start | Code starts at `0x80000000`. The runtime sets the stack, enables the FPU, clears `.bss` and calls `main`. | The vector table is at address 0 in SSRAM1 (4 MiB, which holds the whole image). The runtime enables the FPU and the UART, clears `.bss` and calls `main`. |
| Output | `io.stdout()` and `io.stderr()` write to the NS16550 UART at `0x10000000`. | The CMSDK UART0 at `0x40004000`. |
| Memory | Arenas use the RAM between the end of the image and the stack. | Arenas use 3 MiB of SSRAM2/3 from `0x20000000`. |
| Stack | The last 1 MiB of the default 128 MiB of RAM. | The last 1 MiB of SSRAM2/3, below `0x20400000`. |
| Exit | Returning from `main` exits with status 0 through the SiFive test device at `0x100000`. | Arm semihosting (`SYS_EXIT_EXTENDED`); QEMU needs `-semihosting-config enable=on,target=native`. |

On both boards `io.stdin()` reports end of input, and arenas take memory in
last-in first-out order. A panic runs defers, prints the message (and a stack
trace in debug builds) to the UART, then exits with status 101. Any trap or
fault prints `unexpected trap` and exits with status 102. Generated Dyn code
checks stack space before allocating frames and outgoing argument storage.
Stack overflow prints `stack overflow` and exits with status 104 without
running defers. The runtime reserves 4 KiB of headroom for bounded assembly
helpers; external C and handwritten assembly must manage their own stack use.

The image needs no loader: its program headers place every segment inside RAM,
and the ELF headers are not loaded.

## Memory

Arenas are the only allocator, as on every target. `mem.arena_create` takes
its capacity from one fixed region. Releasing the newest arena returns its
memory to the region; releasing an older one keeps its memory reserved until
every newer arena is released too. For predictable use, create long-lived
arenas first and carve short-lived work out of them with `mem.arena_sub`, or
give `mem.arena_from_buffer` a module-level array.

## Device registers

Use `std/mmio` for hardware registers. Each call performs exactly one access
of the stated width, and the compiler never removes, merges or caches it:

```dyn
use "std/mmio"

const UartData: usize = 0x10000000
const UartStatus: usize = 0x10000005

fn uart_put(byte: u8) {
  for (mmio.load_u8(UartStatus) & 0x20) == 0 {
  }
  mmio.store_u8(UartData, byte)
}
```

Ordinary pointer loads and stores may be combined or removed when the
compiler proves the program cannot observe the difference, so never use them
for devices. Each `mmio` access costs one call.

## Library support

`std/mem`, `std/io`, `std/mmio` and modules built only on them, such as `std/fmt`,
`std/bytes` and the containers, work. Modules that need an operating system
(`std/fs`, `std/net`, `std/process`, `std/thread`, `std/time`) do not
compile for this target. `#syscall` is rejected.

## Limits

- Each board layout is fixed: QEMU `virt` with 128 MiB of RAM and one hart,
  or QEMU `mps2-an500`. Other boards need a different start runtime.
- The runtime reserves about 300 KiB of `.bss` for panic unwinding and trace
  records sized for 64 threads.
- RV32 and Thumb hard- and soft-float release builds use SSA for a conservative
  subset with stack slots for values. Local aggregates, descriptor arguments,
  and string/slice returns are supported. The frontend still rejects any
  returns. Struct and raw-array parameters, arguments and returns use target
  ABI plans, including hidden result pointers and caller-owned copies.
  Unsupported functions use the tree emitter. Checked integer arithmetic and division
  use SSA when the surrounding function is supported. Ordinary integer and
  pointer direct/indirect calls also use SSA. Scalar hard-float arithmetic,
  comparisons, conversions, remainder, memory and calls use raw-bit slots;
  direct Dyn packed variadic and foreign C variadic call sites are supported.
  Protected calls, panic and deferred cleanup also use SSA when supported.
  Internal lowering and resource limits can still require tree fallback.
- `thumbv7em-none` needs a double-precision FPU (Cortex-M7 with FPv5-D16).
  Cores with only single precision, such as the Cortex-M4F, are not
  supported.
- Floating aggregate interoperability is tested against Clang: RV32 uses
  floating/integer argument fields, and Thumb supports homogeneous floating
  aggregates in VFP registers. Large Thumb structures pass by value, with
  core/stack splitting. RV32 wide arguments can split across `a7` and the
  stack. These paths have Clang interoperability tests under QEMU in both
  debug and release builds; physical hardware validation remains pending.

## Debugging

Both 32-bit targets emit DWARF with `--debug-info` (enabled by default in
debug builds). The information includes source lines, frame unwinding,
parameters, locals and 32-bit pointer/slice layouts. Start QEMU with `-S`
and `-gdb tcp::1234`, then connect an architecture-capable GDB with
`target remote :1234`. `tests/bare-debugger.py` checks live nested frames,
locals and return stepping on RV32 and Cortex-M7 when QEMU and GDB are available.

The first physical board profile is NUCLEO-H753ZI. ST lists this
board as active and recommends it as the replacement for the obsolete
NUCLEO-H743ZI. The profile builds flash firmware; hardware qualification is pending.
See [ST's board page](https://www.st.com/en/evaluation-tools/nucleo-h753zi.html).

## NUCLEO-H753ZI flash profile

Build and flash the board example:

```sh
dyn build tests/nucleo --target thumbv7em-none-nucleo-h753zi --output nucleo.elf
openocd -f interface/stlink.cfg -f target/stm32h7x.cfg \
  -c "program nucleo.elf verify reset exit"
```

Connect the STLINK USB port and open its virtual serial port at 115200 baud,
8 data bits, no parity, one stop bit. The example prints
`hello from NUCLEO-H753ZI`. Use a system reset when starting firmware; the
profile assumes the reset HSI clock at 64 MHz and leaves caches disabled.
USART3 TX uses PD8/AF7 with the board's default virtual-COM solder bridges.

Code, constants and the initial writable-data image occupy the 2 MiB flash
region starting at `0x08000000`. Writable data and BSS start at `0x24000000`
in 512 KiB AXI SRAM. Startup copies initialized data from flash and clears
BSS. Arenas use the remaining AXI SRAM. The stack uses the separate 128 KiB
DTCM region ending at `0x20020000`. The linker rejects images exceeding
flash or AXI SRAM. The runtime's unwind buffers consume much of AXI SRAM;
size arenas accordingly (the example uses 64 KiB).

Returning from `main` records zero in `dyn_exit_status` and sleeps. Panic
and fault paths record their nonzero status there. No semihosting debugger
is required. To debug, run OpenOCD without its `program ... exit` command,
then use an Arm-capable GDB:

```text
file nucleo.elf
target extended-remote :3333
monitor reset halt
load
monitor reset halt
break main
continue
```

`tests/nucleo-profile.py` checks vectors, flash/RAM placement, startup symbols
and RAM overflow rejection. With the optional Unicorn package it also runs
startup and the example against CPU/memory emulation, including dirty RAM
and UART-register writes. This does not simulate STM32 peripheral timing or
prove physical-board execution. Hardware qualification is still pending.

Profile references: [UM2407 board manual](https://www.st.com/resource/en/user_manual/um2407-stm32h7-nucleo144-board-stmicroelectronics.pdf),
[RM0433 reference manual](https://www.st.com/resource/en/reference_manual/rm0433-stm32h742-stm32h743-753-and-stm32h750-value-line-advanced-armbased-32bit-mcus-stmicroelectronics.pdf),
and [ST device definitions](https://github.com/STMicroelectronics/cmsis-device-h7/blob/master/Include/stm32h753xx.h).
