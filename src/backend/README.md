# Native backend

The native backend is the compiler's only code generator for native targets. It
reads the checked `DynIrProgram` from `dyn_ir_lower` (after `src/native_opt.c` in
release builds) and writes relocatable objects directly, with no assembler:

- ELF64 for x86-64, AArch64 and RISC-V64 Linux, and RISC-V64 bare metal
- ELF32 for RISC-V32 bare metal (written as ELF64, then narrowed by
  `src/elf_class.h`)
- Mach-O for x86-64 and AArch64 macOS
- COFF for x86-64 and ARM64 Windows

Wasm output is written by `src/codegen_wasm.c`, not by this backend.

## Files

| File | Contents |
| --- | --- |
| `compiler.c` | Entry point used by the compiler (`dyn_native_object`) |
| `driver.c` | Tree emitter: functions, statements, expressions, calls, runtime checks, defers |
| `ssa.inc` | SSA code generation: construction, optimization, register allocation, x86-64 emission |
| `ssa_a64.inc` | AArch64 emission for SSA code generation |
| `ssa_rv64.inc` | RISC-V64 emission for SSA code generation |
| `isa.inc` | x86-64 encodings |
| `a64.inc` | AArch64 encodings |
| `rv64.inc` | RISC-V64 encodings |
| `rv32.inc` | RISC-V32: the 64-bit register model as register pairs, ILP32D calls |
| `t32.inc` | Thumb-2 (ARMv7E-M with FPv5-D16): the same 32-bit model, AAPCS-VFP calls |
| `allocation.inc` | Linear-scan allocation of integer locals to callee-saved registers |
| `vector.inc` | Fixed-bound elementwise integer loops |
| `reachability.inc` | Removal of private functions that nothing references |
| `coff.inc`, `macho.inc` | Translation of the ELF-form symbols and relocations |
| `dwarf.c`, `dwarf.h` | Line, frame and variable debug information |
| `elf64.h` | ELF definitions, so the backend never needs host headers |
| `output.h` | Atomic publication of output files |
| `reentrant-unit.c`, `output-unit.c` | Unit tests for repeated emission and publication |

## Code generation

Optimized builds for x86-64 and AArch64 Linux and macOS, RISC-V64 Linux and
Windows x86-64 and ARM64 use
SSA code generation (`ssa.inc`), modeled on Go's compiler. Each function is
built into SSA form while walking the IR (Braun et al.), then optimized:
constant folding, dominator-based CSE that also removes repeated checks, a
local load reuse pass that shares identical typed reads within one block until
a store, call, copy, or other memory effect invalidates them, a
range prover that removes bounds and overflow checks it can prove, division
by constants through multiplication, and loop-invariant code motion. Small
structs in frame memory that never escape (literals, call results, by-value
parameters) are forwarded: loads take the stored values, copies out of them
become plain stores, and stores nothing reads are removed. Constants stored in
one block reach loads in the blocks it dominates. The prover also removes
null and alignment checks on addresses of globals and frame memory. Loop
nests whose inner loop carries a floating accumulator, such as matrix
multiply, are unrolled by two and jammed: two independent sums run side by
side, each adding the same terms in the same order. A function that returns
`f(...) + x` with checked unsigned 64-bit addition, and has no effects or
checks other than overflow checks, keeps the sum in an accumulator and jumps
back to its start instead of making the last call. Dense
`case` statements become jump tables. On x86-64 System V, a recursive
function whose first pure unsigned guard returns an argument can bypass frame
setup on that path. A two-statement unsigned recurrence with two decreasing
self calls can also pack its first eight proved byte-sized results into a
constant. Larger arguments execute the original checked code. Small leaf
functions inside loops are inlined under a separate size budget at O2; their
arguments are captured once, and constant subtrees are shared. Runtime checks
retain their originating callee through inlining, including tree fallback and
cleanup. Linear-scan register allocation runs over all values, with clobber-aware live intervals and hints that coalesce
moves. Emission runs twice so the second pass can use short branches.

RISC-V32 always uses the tree emitter. Each model register is a pair of
32-bit registers (low words where RV64 keeps the value, high words in s2-s9),
so every operation keeps its 64-bit meaning; `usize` and pointers are 32 bits
in memory and are normalized like `u32`. Division, checked multiplication and
64-bit integer/float conversion call helpers in the start runtime.

Thumb-2 (`thumbv7em-none`) uses the same 32-bit model, also only through the
tree emitter. ARMv7-M has twelve free core registers, too few for sixteen
words, so the low words and the high words of A and C stay in core registers
and the other high words in callee-saved VFP registers (s16-s21). The frame
pointer r11 is biased by 4092 so one 12-bit offset reaches most locals.
Comparisons store their operands in s24-s27 and each branch evaluates its
condition from them, as RV32 does; add, subtract and negate keep their flags
in s28 for overflow checks. Calls follow AAPCS-VFP, except that structs over
64 bytes pass as a pointer to a copy. Aligned aggregate copies and zero fills
use word accesses, with byte prefixes and tails; copies preserve overlap
semantics. Both 32-bit targets emit DWARF with target-sized addresses and
frame rules, including the biased Thumb frame pointer.

A function the SSA path cannot build yet falls back to the tree emitter;
`--opt-remarks` reports the line of `ssa.inc` that stopped it. Debug builds
use the tree emitter. Windows ARM64 SSA reserves callee-saved GP registers
and spills values that cross calls, so it can reuse the canonical Windows
unwind records and stack probing. `DYN_NO_SSA=1` selects the tree
emitter everywhere. SSA code
keeps the runtime checks, their order and their messages, so both paths
produce the same output; `tests/native-ssa.py` checks that across targets.

`driver.c` emits named operations from the target `.inc` file over a small
register model: an accumulator, a descriptor word, an operand register, scratch
and copy registers, the frame pointer and an expression stack. AArch64 pushes
are 16 bytes so SP stays aligned. In release builds, integer locals that never
escape and do not live across deferred cleanup move to callee-saved registers.

Runtime-check failures share one failure path per check kind and originating
function; later checks with the same origin branch to it. Paths that run pending defers and then panic, keep
unwinding or return share one cleanup ladder per defer stack.

Code generation records symbols and relocations in ELF form. `coff.inc` and
`macho.inc` translate them: COFF and Mach-O keep addends in the relocated bytes,
Mach-O page references take a preceding `ARM64_RELOC_ADDEND`, and every Darwin
symbol gains a leading underscore. Mach-O objects lay sections out from address
zero, so their DWARF needs no relocations; macOS builds keep the object beside
the output (`<output>.dynnative.o`), where the executable's debug map finds it.
Windows objects carry DWARF in COFF sections (GDB and LLDB read it; Visual
Studio and WinDbg need CodeView, which is not written), plus `.pdata`/`.xdata`
unwind tables describing the fixed prologue. Global initializers run from
`main` on every target; only ELF also lists them in `.init_array`. Mutable
globals are zero-fill storage.

## Calling conventions

x86-64 Linux and macOS follow System V.

AArch64 follows AAPCS64 for C-visible types: eight GP and eight FP argument
registers, HFAs in consecutive FP registers, other composites up to 16 bytes in
GP pairs, larger composites through a pointer to a caller-owned copy, and X8 for
indirect results. Dyn-only arrays and payload enums are passed as flattened
leaves and returned through memory, since every function in a build is emitted
by the same backend. Apple's variant packs stack arguments narrower than eight
bytes at their natural size and passes every C variadic argument on the stack.

Windows follows the Microsoft x64 convention: the first four arguments take
RCX, RDX, R8 and R9 or XMM0-3 by position, structs of 1, 2, 4 or 8 bytes travel
as integers and other structs through a pointer to a caller-owned copy, RCX
carries the hidden result pointer, and variadic floating arguments are copied
into the matching integer register. Every call reserves the 32-byte home area,
where functions also save the callee-saved RSI and RDI. Frames of 4 KiB or more
call `__chkstk` to touch each guard page in order.

## Failure behavior and limits

Every function is validated while generating an in-memory buffer. Unsupported
IR fails before the output file is opened, even when earlier functions were
valid, and an existing output is never replaced. Objects are published through
a private sibling temporary file and an atomic rename.

Bounds: 16 MiB each for machine code, read-only data, symbol names, and
relocation storage; 32,768 functions and 32,768 globals; 4096 locals per
function (including parameters) and 16 MiB of frame storage; 16 MiB per
aggregate type; 512 parameters and 512 argument eightbytes per call; 4,194,304
IR expressions/statements; 1024 recursive expression edges and 1024 nested
statement blocks; 4096 defers per function. Each emission owns a zeroed,
heap-allocated context, so repeated and concurrent emission is safe.

## Tests

From the compiler directory:

- `just test-backend` builds the standalone `build/scalar-backend` and the unit
  tests, then runs `tools/backend/test.py`. It checks ELF sections, symbols and
  relocations, compares 57,353 values and 518 panics against the compiler's own
  debug and release output and a mathematical model, and checks rejection of
  unsupported input.
- `just test-native-debug` runs `tools/backend/check-compiler.py`: routing,
  frontend, cache and runtime contracts of the built compiler.
- `just test-native-a64`, `test-native-windows` and `test-native-macos` run
  `tools/backend/native-differential.py`. It builds a 3,300-case corpus for the
  target and for x86-64 Linux, runs every case on both (under `qemu-aarch64`,
  `qemu-riscv64`, wine or a matching host), and compares status, stdout and
  stderr. CI builds the corpora with `--stage` on Linux, where it also records
  the x86-64 Linux results, and runs them on native runners with `--run`.
- `tools/backend/feature-contracts.py` and `global-contracts.py` cover enums,
  `any`, variadics, globals, initializers and shared constructors.
- `tests/native-ssa.py` checks division by constants against hardware
  division and compares SSA and tree-emitter output on x86-64 and AArch64.
- `tools/bench/run.py` times five kernels against `cc -O2` and Go.
- `tools/backend/object-hashes.py --compare` checks that a refactor leaves
  emitted objects byte-identical.

To run a sanitized frontend and backend build without replacing the normal
binary:

```sh
BUILD=/tmp/dyn-backend-sanitize \
  CFLAGS='-O1 -fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie' \
  python3 tools/backend/build.py
BUILD=/tmp/dyn-backend-sanitize DYN="$PWD/build/dyn-release" \
  python3 tools/backend/test.py
```
