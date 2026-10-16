# Independent compiler toolchain

Build without LLVM headers, libraries, Clang, LLD, or target assemblers:

```sh
DYN_WITH_LLVM=0 CC=gcc BUILD=build/no-llvm python3 tools/build.py dyn host
DYN_SDK="$PWD" build/no-llvm/dyn build example --release --output example-bin
```

The host C compiler builds the compiler itself. Python assembles the checked-in
runtime assembly subset directly into ELF, Mach-O, and COFF objects; Dyn compiles
the portable runtime support. Unknown assembly syntax fails the build. No cached
Clang-produced object blobs or external target compilers participate. `host` now
includes runtimes for Linux x86-64, Linux ARM64, macOS ARM64, Windows x86-64, browser
Wasm, and WASI Preview 1. Host SDK packages contain these cross-target runtimes.
Cross-compiling a program does not provide third-party target libraries or make
every SDK package portable.

The LLVM-enabled reference build remains available for differential testing.
Select `--backend native` there to use the same independent emission paths.

## Textual outputs

`--emit-ir` writes real LLVM IR to `<output>.ll` using a standalone syntax writer.
It shares semantic lowering with the reference backend and includes ABI lowering,
checked failures, cleanup, initialization, and requested debug metadata. LLVM is
not loaded or invoked to produce the file. LLVM tools are optional consumers of
this interchange format, not compiler dependencies.

`--emit-asm` writes reassemblable target assembly to `<output>.s`. Native output
preserves emitted instruction bytes, sections, symbols, relocations, constructors,
and debug/unwind data. Much of the native instruction stream uses `.byte`
directives; this is an exact assembler representation, not a fully mnemonic
instruction listing. Wasm output uses symbolic stack instructions and type
directives. Export does not replace the native object with an LLVM-generated one.

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
  arguments. Calls with side effects or nonconstant arguments remain calls.

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

The independent optimizer does not yet provide LLVM's vectorizer, general
inliner, register allocator, or equivalent performance across programs. Passing
correctness tests is not a claim of that performance parity. O1 is currently an
independent-backend option; the reference LLVM path retains O2/O3.

## Qualification

`tests/no-llvm.py` builds from scratch with LLVM tool sentinels, checks binary
dependencies, executes native/Wasm contracts, and repeats cross-target builds from
a relocated SDK. macOS and Windows run equivalent host qualification.

`tests/cross-runtime.py` generates runtime objects with an empty PATH, checks all
four native executable/shared formats, and executes host programs plus Linux
ARM64 under QEMU when installed. Runtime tests cover overlapping and unaligned
memory operations, threads/atomics, panic cleanup, and exact floating remainder.
`tests/text-output.py`, `tests/native-assembly.py`, and `tests/wasm-assembly.py`
use optional external tools only as independent parser/assembler oracles and
execute reconstructed outputs. `tests/native-optimization.py` checks code changes
and observable behavior across levels, CPU selection, and hot/cold profiles.
