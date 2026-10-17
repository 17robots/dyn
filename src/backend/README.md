# Native backend

The native backend is the compiler's only code generator for native targets. It
reads the checked `DynIrProgram` from `dyn_ir_lower` (after `src/native_opt.c` in
release builds) and writes relocatable objects directly, with no assembler:

- ELF64 for x86-64, AArch64 and RISC-V64 Linux
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
| `allocation.inc` | Linear-scan allocation of integer locals to callee-saved registers |
| `vector.inc` | Fixed-bound elementwise integer loops |
| `reachability.inc` | Removal of private functions that nothing references |
| `coff.inc`, `macho.inc` | Translation of the ELF-form symbols and relocations |
| `dwarf.c`, `dwarf.h` | Line, frame and variable debug information |
| `elf64.h` | ELF definitions, so the backend never needs host headers |
| `output.h` | Atomic publication of output files |
| `reentrant-unit.c`, `output-unit.c` | Unit tests for repeated emission and publication |

## Code generation

Optimized builds for x86-64 and AArch64 Linux and macOS and RISC-V64 Linux use
SSA code generation (`ssa.inc`), modeled on Go's compiler. Each function is
built into SSA form while walking the IR (Braun et al.), then optimized:
constant folding, dominator-based CSE that also removes repeated checks, a
range prover that removes bounds and overflow checks it can prove, division
by constants through multiplication, and loop-invariant code motion. Dense
`case` statements become jump tables. Linear-scan register allocation runs
over all values, with clobber-aware live intervals and hints that coalesce
moves. Emission runs twice so the second pass can use short branches.

A function the SSA path cannot build yet falls back to the tree emitter;
`--opt-remarks` reports the line of `ssa.inc` that stopped it. Debug builds
and Windows use the tree emitter. `DYN_NO_SSA=1` selects the tree
emitter everywhere. SSA code
keeps the runtime checks, their order and their messages, so both paths
produce the same output; `tests/native-ssa.py` checks that across targets.

`driver.c` emits named operations from the target `.inc` file over a small
register model: an accumulator, a descriptor word, an operand register, scratch
and copy registers, the frame pointer and an expression stack. AArch64 pushes
are 16 bytes so SP stays aligned. In release builds, integer locals that never
escape and do not live across deferred cleanup move to callee-saved registers.

Runtime-check failures share one failure path per check kind in each function;
later checks branch to it. Paths that run pending defers and then panic, keep
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
