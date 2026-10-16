# Independent compiler toolchain

Build without LLVM headers, libraries, Clang, LLD, or target assemblers:

```sh
CC=gcc BUILD=build/no-llvm python3 tools/build.py dyn host
DYN_SDK="$PWD" build/no-llvm/dyn build example --release --output example-bin
```

The host C compiler builds the compiler itself. Python assembles the checked-in
runtime assembly subset directly into ELF, Mach-O, and COFF objects; Dyn compiles
the portable runtime support. Unknown assembly syntax fails the build. No cached
Clang-produced object blobs or external target compilers participate. `host` now
includes runtimes for Linux x86-64, ARM64 and RISC-V64; macOS x86-64 and ARM64;
Windows x86-64 and ARM64; browser Wasm; and WASI Preview 1. Host SDK packages contain these cross-target runtimes.
Cross-compiling a program does not provide third-party target libraries or make
every SDK package portable.

Independent emission is now the only compiler backend. The LLVM implementation
and its C++ ThinLTO bridge have been removed. `--backend llvm` reports an error.
External LLVM tools remain optional format-validation oracles in tests.

## Textual outputs

`--emit-ir` writes real LLVM IR to `<output>.ll` using a standalone syntax writer.
It uses the compiler’s semantic lowering and includes ABI lowering,
checked failures, cleanup, initialization, and requested debug metadata. LLVM is
not loaded or invoked to produce the file. LLVM tools are optional consumers of
this interchange format, not compiler dependencies.

`--emit-asm` writes reassemblable target assembly to `<output>.s`. Native output
preserves emitted instruction bytes, sections, symbols, relocations, constructors,
and debug/unwind data. Recognized AArch64 instructions and unambiguous x86-64
instructions use mnemonics. Other x86-64 instructions retain exact bytes with
readable annotations; unsupported encodings retain byte directives explicitly.
RISC-V output also annotates recognized instructions while retaining their bytes.
The exporter does not guess instruction boundaries after an unknown x86 encoding. Wasm output uses symbolic stack instructions and type
directives. When assembling Wasm output with Clang, pass
`--target=wasm32 -mbulk-memory` for its memory copy/fill instructions.
Export does not replace the native object with an LLVM-generated one.

These switches retain normal object generation and linking. Add `--no-link` to
stop before linking. Library object export uses
`--shared --emit-object --no-link`. Existing text output files are preserved when text
publication fails.

## Independent release optimization

`--release --opt-level 1`, `2`, or `3` selects real conservative passes:

- **O1:** fold scalar integer and boolean expressions while preserving checked
  overflow, invalid shifts, division errors, and evaluation effects.
- **O2 (default):** also propagate immutable local constants and remove unchosen
  constant branches.
- **O3:** also specialize bounded pure scalar function calls with constant
  arguments. It also inlines eligible direct calls with dynamic arguments,
  preserving argument evaluation and cleanup. Unsupported call contexts remain calls.

`--opt-remarks` reports actual transformations. `--cpu native` is restricted to
the host target and resolves the implemented host features into the cache key.
On x86-64 hosts with BMI2, variable shifts use `shlx`, `shrx`, and `sarx`; other
hosts use the baseline ISA. It does not imply every host feature is tuned.

`--sample-profile FILE` accepts a strict text sample-profile subset:

```text
calculate:1000:10
 1: 500
 2.1: 500
```

Function totals control constant-call specialization budgets: hot functions
(total at least 100) receive a larger budget, cold functions a smaller one.
Profiles enable this pass at O2 too. Empty, malformed, overflowing, binary,
inline-stack, and callsite profile forms are rejected. This is independent
profile-guided specialization, not LLVM's complete sample-PGO pipeline.

O3 native emission allocates eligible integer locals to callee-saved registers on
Linux and macOS. Address-taken locals stay in memory; debug, Windows, RISC-V, and functions
with deferred cleanup retain stack allocation. Structured liveness includes loop
backedges. O3 also vectorizes proven fixed-bound local-array loops using SSE2 or
NEON for 32/64-bit wrapping addition, subtraction, and bitwise operations, with
scalar tails. Unsupported loops remain scalar; Wasm does not use this SIMD pass.

These passes do not imply LLVM-equivalent performance across programs. Run
`tools/optimization-benchmark.py` for paired O2/O3 measurements and emitted-code
checks on the current host.

## Qualification

`tests/no-llvm.py` builds from scratch with LLVM tool sentinels, checks binary
dependencies, executes native/Wasm contracts, and repeats cross-target builds from
a relocated SDK. macOS and Windows run equivalent host qualification.

`tests/cross-runtime.py` generates runtime objects with an empty PATH, checks all
seven native executable/shared targets, and executes host programs plus Linux
ARM64 and RISC-V64 under QEMU when installed. Runtime tests cover overlapping and unaligned
memory operations, threads/atomics, panic cleanup, and exact floating remainder.
`tests/text-output.py`, `tests/native-assembly.py`, and `tests/wasm-assembly.py`
use optional external tools only as independent parser/assembler oracles and
execute reconstructed outputs. `tests/native-optimization.py` checks code changes
and observable behavior across levels, CPU selection, and hot/cold profiles.
