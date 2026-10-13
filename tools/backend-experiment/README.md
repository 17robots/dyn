# Native debug backend

This backend consumes the checked `DynIrProgram` produced by `dyn_analyze` and
`dyn_ir_lower` and writes x86-64 Linux ELF64 relocatable objects directly, without
LLVM or an assembler. The default `dyn` and `dyn-release` compilers link it on
x86-64 Linux hosts (`-DDYN_NATIVE_BACKEND`); other hosts build without it.

## Compiler integration

`dyn build` and `dyn run` select the code generator with `--backend`:

- `auto` (default): debug builds for an x86_64-linux host and target use native
  emission. If the program exceeds a native capacity or uses an unsupported
  construct, the compiler silently uses LLVM instead (`--verbose` prints a note).
- `native`: native emission is required. Unsupported programs fail with
  `use --backend llvm`; an existing output is never replaced.
- `llvm`: always use LLVM.

`--release`, `--shared`, `--emit-ir`, `--emit-asm`, CPU/feature selection,
optimization remarks and non-x86_64-linux targets always use LLVM; combining them
with `--backend native` is an error. Debug builds emit DWARF by default: lines,
frames, parameters, and typed locals nested in lexical blocks, with payload enums
as `tag` plus a `payload` union; `--debug-info` is accepted.

Native emission handles the complete merged program in one object. Executables use
the whole-executable build cache, keyed separately from LLVM builds; LLVM module and
chunk caches are not used, because native emission of the whole program is cheaper
than restoring them. A private temporary object is linked unless `--no-link` or
`--emit-object` requests `<output>.o`.

`dyn-legacy` (Tree-sitter parsing, LLVM emission) is the differential reference.
`just test-native-debug` runs routing/fallback/runtime contracts against it, and
`just test-native-strict` runs the regression suite through
`strict-dyn.py`, which turns every silent fallback into a failure.
`tests/native-debugger.py` checks breakpoints, backtraces, parameters and typed
locals in gdb.

## Supported slice

- Host and target: x86-64 Linux, little-endian ELF64, System V calling convention.
- Functions with zero to 256 parameters and a supported scalar, descriptor, struct, or void return. Bodies may
  contain returns, locals/assignments, expression statements, nested
  `if`/`else`, and conditional or infinite `for` loops. Break/continue support
  nested and labeled loop targets; early returns pop tracing exactly once.
  Non-void functions require a return on every structurally reachable path; constant-condition reasoning is
  not used to accept a missing return.
- Types: signed/unsigned 8-, 16-, 32-, and 64-bit integers, `isize`, `usize`, `bool`, `f32`, `f64`, typed/raw pointers, and typed function pointers.
- Integer, enum, and `any` cases support singleton/range/multiple patterns, wildcard
  arms, value bindings, and mutable enum payload bindings. The checked frontend establishes exhaustiveness.
- Scalar integer ranges support forward/reverse and inclusive/exclusive bounds.
  Bounds evaluate once, left to right. The induction counter is separate from the
  mutable binding; continue steps the counter, and inclusive extrema stop before
  increment/decrement can overflow. Nested/labeled loop control works across ranges.
- Void functions support explicit and implicit returns; discarded expressions
  retain evaluation and runtime guards.
- Direct calls to supported functions in the same program, including forward,
  recursive, and mutually recursive calls. Up to 256 scalar arguments evaluate
  left to right; nested calls preserve earlier arguments and surrounding temporaries.
  Integer/pointer arguments use six GP registers; floating arguments use eight
  SSE registers independently. Overflow arguments use source-ordered stack slots. Calls align the stack for System V and normalize boolean return values.
  Incoming stack parameters are copied into local frame slots before tracing.
- Foreign calls use the same scalar ABI. C variadics preserve default promotions,
  independent GP/SSE register exhaustion, stack spills, and the SysV AL vector count.
  Typed indirect calls evaluate
  and check the callee before evaluating arguments (`function.nonnull.ok`), retain
  its address across nested argument calls, and support scalar/void returns.
  Function-address loads use GOT relocations, including foreign functions.
- Expressions: integer/bool constants, parameter reads, bitwise `&`, `|`, `^`, `~`,
  boolean `!`, checked or wrapping `+`, `-`, `*`, unary `-`, division/remainder,
  and left/right shifts. Integer comparisons preserve signedness; bool equality
  and inequality are supported. `&&` and `||` short-circuit, preserving evaluation
  order and skipping guards in an unselected right operand. Shift counts are unsigned integers or inferred unsigned literals.
- Floating expressions support constants, negation, `+`, `-`, `*`, `/`, comparisons,
  locals, calls, and f32/f64 conversions. Comparisons preserve ordered IEEE behavior,
  with unordered `!=`; division preserves IEEE infinities/NaNs rather than adding
  integer-style panic checks. Float return bits survive trace cleanup.
- Checked generic instances use their concrete IR types, mangled symbols, and
  readable debug names. Uninstantiated templates produce no machine code or symbols.
- Plain enums retain their declared integer tag width; integer-to-enum casts check
  declared tags (`enum.cast.ok`), including signedness at 64-bit boundaries. Payload
  enums use the production layout and LLVM aggregate calling convention. `any`
  stores a type ID and pointer to an eagerly copied value. Cases copy typed bindings;
  enum pointer bindings alias original payload storage. Cross-backend callbacks cover
  payload enum arguments and returns.
- Native variadics pack typed values or boxed `any` values into caller-owned storage,
  evaluate arguments left to right, and pass data/count after fixed parameters.
  Empty packs, aggregate elements, deferred captures, and register exhaustion are covered.
- Globals support typed zero storage, scalar constants, mutable aggregate/descriptor
  storage, foreign symbols, function-address values, and runtime initializers in
  checked IR dependency order. Static scalar, aggregate, string and function-pointer
  constants use relocated `.data.rel.ro`; mutable storage uses
  `.data`. Reads/writes honor declared widths even under ELF symbol interposition.
  A guarded initializer serves ELF `.init_array` loading and freestanding `main`
  entry. Initializer guards preserve production names and panic traces.
  Constant aggregate fields retain defaults before explicit overrides.
- Pointer dereferences check nullness and pointee alignment, matching
  `pointer.nonnull.ok` and `pointer.aligned.ok`. Address-taking supports locals, scalar globals, fields, and indexed storage; loads/stores honor pointee width. Pointer/integer casts preserve
  LLVM truncation/extension rules, and equal-width integer/float bitcasts preserve bits.
  Pointer assignment/compound-assignment alias and panic ordering is compared with
  the current GCC-built production compiler. The production C lowering itself uses
  unspecified C argument evaluation order for plain assignments; portability of
  that order is not established by this experiment.
- Deferred calls capture callee/arguments eagerly; deferred blocks read current storage.
  Scope exits, returns, break/continue, and failing checks run reverse-order cleanup.
  Calls with pending cleanup use the existing Linux `dyn_unwind_set/link/unlink/continue`
  runtime context, preserving caller cleanup and exact panic traces across recursion.
  A panic inside cleanup replaces the active panic as in production.
- Fixed arrays and structs support zero initialization, nested literals, field defaults,
  local storage, assignment, address-taking, and overlapping copies. Field offsets honor
  declared alignment and packed layouts. Loads/stores through external pointers use
  exact widths; protected-page tests cover partial eightbyte reads and writes.
- Array/slice indexing preserves index-before-base evaluation and checks `index.ok`.
  Slicing arrays, slices, and typed pointers checks ordering and bounded-source length
  (`slice.order.ok`, `slice.bounds.ok`); raw pointer slices retain pointer guards.
  String literals and descriptor length reads are supported. Descriptors use two words,
  preserved across direct/indirect calls, register exhaustion, deferred captures, and returns.
- Struct arguments/returns use SysV INTEGER/SSE eightbyte classification. Mixed classes,
  floating vectors, and independent register banks are supported; insufficient registers
  move the entire struct argument to the stack. Large/unaligned packed structs use by-value
  stack arguments and hidden return storage. Direct foreign calls and cross-backend typed
  callbacks are checked against C/LLVM. Array-by-value calls follow the current production LLVM native convention, described below.
  Deferred aggregate arguments and return values retain value snapshots before cleanup.
- Array-by-value arguments flatten scalar leaves, including nested arrays/structs,
  into independent GP/SSE registers and eightbyte spill slots without struct rollback.
  Production LLVM native array returns allow three GP values and four FP values:
  the latter use XMM0/XMM1 plus x87 ST0/ST1. Larger returns use hidden storage.
  This is the pinned production LLVM convention, not the C array parameter ABI;
  cross-backend callback tests verify both directions and narrow leaf widths.
- Array/slice iteration supports value/pointer bindings, reverse iteration, nested
  and labeled control, early returns, and cleanup. Value iteration snapshots fixed
  arrays; slice iteration snapshots the descriptor and observes shared element storage.
  Pointer iteration aliases original storage. Each collection evaluates once.
- Integer/float conversions follow the defined LLVM conversion domain. Unsigned
  64-bit conversions handle the high bit without signed overflow; f32/f64→integer
  truncates toward zero. NaN/infinite/out-of-range FP→integer is outside LLVM's
  defined conversion domain; this experiment adds no new runtime check for it.
  Float remainder uses `fmod`/`fmodf`, as LLVM does, and requires libm at link time.
- Explicit `#panic` uses the runtime unwind mechanism, which owns the message before
  cleanup can mutate its backing storage. Tests include replacement panic in cleanup,
  recursive cleanup output, exact traces, and both debug/release production oracles.
  Declaring another defer inside a cleanup remains explicitly unsupported.
- `main` returns the production exit code zero and initializes globals after its
  debug trace entry. `#syscall` evaluates up to seven inputs left to right and uses
  the existing `dyn_syscall6` runtime ABI. The standalone single-file driver uses
  production source merging for reflection prelude injection and original location
  maps; `#typeof` metadata already lowered into checked aggregates is supported.
  Calling `main` as an ordinary function remains explicitly unsupported.
- Integer casts truncate or extend using source signedness, matching LLVM;
  implicit integer conversions extend. Narrow parameters/returns use the SysV
  integer class, including stack arguments and foreign/indirect calls.
- Scalar locals have fixed frame slots, including zero initialization when no
  initializer is present. Plain and compound assignments retain existing checked
  arithmetic; wrapping updates use an explicit `#wrap` expression. Loop-local
  declarations initialize on every iteration.
- Checked arithmetic uses signed overflow or unsigned carry/borrow flags. Unsigned
  multiplication uses the full-width `mul` instruction. Wrapping arithmetic keeps
  the low declared-width bits. Narrow results are normalized with sign/zero
  extension; checked operations additionally verify the result fits that width. The checked frontend's signed-minimum literal marker is preserved.
- Division and remainder reject zero divisors (`divide.ok`) and signed minimum
  divided by `-1` (`division.overflow.ok`), including remainder. Signed division
  truncates toward zero; the remainder retains the dividend's sign.
- Shifts require an unsigned count below the operand width (`shift.count.ok`). Signed right
  shifts preserve the sign. Checked left shifts reject lost value/sign bits
  (`overflow.ok`); wrapping left shifts keep the low declared-width bits. Neither shift
  form relies on x86's hardware count masking for language semantics.
- `#wrap` never suppresses divide-by-zero, signed division overflow, or invalid
  shift counts. The frontend rejects a wrapper containing only `/`, `%`, or `>>`;
  tests place these operations inside valid wrapping expressions with `+ 0`.
- On overflow, generated code calls the existing `dyn_panic(pointer, length)` ABI
  with LLVM's `runtime check failed (CHECK) in FUNCTION` message. Panic paths
  restore stack alignment before the call, including failures inside nested expressions.
- `--debug` adds the existing `dyn_trace_push`/`dyn_trace_pop` ABI, with the original
  source path, line, and function name. Normal returns preserve the scalar result
  across `dyn_trace_pop`. Without `--debug`, emission omits trace calls.

Each function saves parameters and locals in its stack frame, rounded to 16 bytes. Recursive expressions use
balanced stack pushes. The emitter preserves `rbp` and does not use other
callee-saved registers. Calls may target supported program/foreign functions,
typed callbacks, or the runtime functions above.

Objects contain `.text`, `.rodata`, `.data`, `.rela.text`, `.init_array`, `.rela.init_array`, `.data.rel.ro`, `.rela.data.rel.ro`, `.symtab`, `.strtab`, `.shstrtab`,
and a non-executable `.note.GNU-stack`. RIP-relative data references use
`R_X86_64_PC32`; runtime and direct calls use `R_X86_64_PLT32`; function addresses
use `R_X86_64_GOTPCREL`; constructor pointers use `R_X86_64_64`. Private functions, globals and initializer helpers use local ELF bindings;
all locals precede the first global symbol and relocations use remapped symbol IDs.
Public/foreign symbols and the entry point retain global bindings. Runtime ABI names
are reserved so source declarations cannot replace a guard or trace function.
`exit` and `_exit` are also rejected: production LLVM renames these symbols, and
this experiment does not yet share that symbol policy. Foreign/local link-name
collisions are likewise rejected rather than silently binding the wrong function.

Unused type metadata
does not generate code. This experiment does not
establish full language coverage, module/import policy, debugger integration, full symbol policy,
or production cache compatibility; it is not a production backend replacement.

## Failure behavior and limits

The emitter itself never falls back; the compiler's `--backend auto` policy does.
Every function is validated while generating an in-memory buffer. Unsupported IR fails before the output file is opened, including
when earlier functions were valid. Unreachable statements and unselected branches
are still validated; unsupported constructs cannot hide behind an early return or
a constant condition. Existing output files survive unsupported-input
failures. Objects publish through a private sibling temporary file and atomic rename;
write/close/rename failures preserve the previous destination. This establishes atomic
visibility, not durability across a system crash.

Bounds: 16 MiB each for machine code, read-only data, symbol names, and
relocation storage; 32,768 functions and 32,768 globals; 4096 locals per function
(including parameters) and 16 MiB of frame storage, including hidden eightbyte slots for
temporaries/ranges/cases/captures/unwind state; 16 MiB per aggregate type;
512 parameters and 512 argument eightbytes per call; 4,194,304 IR expressions/statements;
1024 recursive expression edges and 1024 nested statement blocks; 4096 defers per function. Exceeding a
limit fails. The frontend's own limits also apply. The emitter accepts checked
compiler-owned IR, not arbitrary serialized IR. Each object invocation owns a zeroed,
heap-allocated emission context; repeated and concurrent emission tests verify isolated
state, deterministic output, and recovery after failure. Fixed capacities still apply.

## Commands

From the compiler directory, with existing grammar and Tree-sitter dependencies:

```sh
python3 tools/backend-experiment/build.py
build/scalar-backend input.dyn output.o
build/scalar-backend --debug input.dyn debug-output.o
python3 tools/backend-experiment/test.py
```

Objects with checked operations require the existing Dyn runtime at link time.
Debug objects also require its tracing functions. For example, using runtime
artifacts built by the compiler's normal build:

```sh
cc -shared -Wl,--no-undefined output.o \
  build/dynrt_shared.o build/dynrt_support_pic.o -lm -o output.so
```

`build.py` honors `CC`, additional `CFLAGS`, `BUILD`, and `TS_DIR`. It builds
`build/scalar-backend` and the native context/output units, then runs the output unit.
Tests require the production `build/dyn-release` executable
(or `DYN` override), a C compiler/linker, and `readelf`. The test compiles the
unmodified native runtime sources itself for its temporary shared libraries.

`python3 tools/backend-experiment/feature-contracts.py` adds 332 value checks and
36 panic subprocess checks for enums, `any`, and variadics in LLVM/native debug
and release libraries. It also checks cross-backend payload callbacks, aggregate
assignment snapshots, mutable payloads, type identity, argument order, register
exhaustion, and deferred pack cleanup. `--oracle-only` validates the LLVM baseline.
Run `build/backend-reentrant-test` for repeated/concurrent object emission and
allocation-failure recovery; `build/backend-output-test` checks atomic publication
under short writes, interrupted writes, failures, and concurrent readers/writers.
`python3 tools/backend-experiment/global-contracts.py` adds 52 checks covering runtime
global ordering, foreign/aggregate/descriptor/function-pointer storage, reflection,
syscalls, shared constructors, freestanding entry, constant data protection, private
symbol isolation from linked C definitions, and exact initializer panic traces.

The focused test inspects ELF sections, symbols, relocation types/addends, and
permissions. It compares boundary/random value invocations against production
LLVM debug and release output and a mathematical model for checked operations.
It compares 57,353 value invocations and 518 failing invocations in isolated subprocesses, requiring exact
stderr, exit status 101, and expected cleanup stdout (empty for other guards). Nested-expression failures exercise stack
alignment. Short-circuit cases verify skipped division by zero and left-before-right
panic order. Direct-call cases cover register arities zero through six and stack arities
7, 8, 9, 16, 32, and 256, nested argument
evaluation, signed/bool stack values, wide offsets, forward/self/mutual recursion,
bool returns, and exact multi-frame panic
traces. Local/loop cases cover zero initialization, all integer compound operators,
nested and labeled break/continue, early returns, repeated loop initialization,
checked/wrapping updates, and frames beyond the 8-bit displacement range. Case/range tests cover signed
extrema, reversed/empty intervals, endpoint overflow avoidance, mutable bindings,
and labeled control. Indirect-call tests include native host callbacks, null-before-
argument panic ordering, void calls, stack arguments, foreign function addresses,
and exact panic trace chains. Narrow-integer tests cover each width/signedness,
checked/wrapping arithmetic and shifts, division extrema, casts, bitwise operations,
stack arguments, libc calls, and typed native callbacks. Float cases cover NaN,
infinity, signed zero, both precisions, mixed GP/SSE bank exhaustion, up to 256
float arguments, and native callbacks; an assembly probe verifies call alignment.
Generic tests include recursion and exact instance panic traces. Global tests cover
zero/static initialization, mutation, old-value capture across a mutating RHS,
function-pointer storage, and executable symbol overrides with adjacent canaries.
Pointer cases exercise alignment/null failures, target-before-RHS panic order,
retargeted aliases, width canaries, heap FFI, and bit-preserving float conversions.
An assembly interposer separately checks stack alignment at callee entry;
a call counter proves the probe runs. Each panic subprocess first traverses every early/nested return path
to verify trace cleanup across all branches. Shared
release tests use the same runtime configuration as production shared builds:
no emitted function trace calls, but the runtime still prints its trace header.

Twenty-two unsupported/malformed inputs verify exact rejection status, expected
messages, and preservation of new/existing outputs. A separate source-size case
checks the input bound. All subprocess checks reject sanitizer diagnostics; a
sanitizer crash cannot count as successful rejection. These are correctness
checks, not performance evidence.

To run a sanitized frontend/emitter build without replacing the normal binary:

```sh
BUILD=/tmp/dyn-backend-sanitize TS_DIR="$PWD/build/deps/tree-sitter-dyn" \
  CFLAGS='-O1 -fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie' \
  python3 tools/backend-experiment/build.py
BUILD=/tmp/dyn-backend-sanitize DYN="$PWD/build/dyn-release" \
  python3 tools/backend-experiment/test.py
```

Further backend work must qualify each new operation's safety behavior, broaden
SysV aggregate ABI coverage, aggregate iteration,
and defer unwinding.
Production migration requires separate qualification; this experiment does not
supply that gate.

## Matched-IR benchmark

Run `just bench-backend-experiment` from the compiler directory. For a short
correctness smoke:

```sh
python3 tools/backend-experiment/benchmark.py --sizes 4 --runs 1 --calls 1000
```

The harness gives both emitters identical prepared IR in fresh processes. It
reports preparation and object-emission time separately, alternating emitter
order over five samples by default. Emission includes target initialization and
object writes, but excludes parsing, IR preparation, linking, and process startup.
Debug mode enables runtime traces with DWARF disabled for both emitters; release
uses LLVM's normal optimization policy. This is not a whole-compiler benchmark.

The generated workload contains 65, 257, and 1,025 scalar functions with branches,
wrapping arithmetic, and direct calls. Each generated function is checked against
a mathematical model through both objects. A separate timed runner repeatedly
calls one exported function, checking matching checksums. That runtime test is a
small call/arithmetic workload, not a general application-performance result; it
does not measure the newly supported loops.

`build/backend-benchmark.json` records all samples, medians, object sizes, commands,
source, implementation, and runtime object hashes, build recipes, current tool
versions, and runtime checksums. The script refreshes its explicit build targets
before timing. Peak RSS
covers the entire matched harness, including preparation and shared LLVM linkage;
it must not be presented as standalone scalar-emitter memory usage. Run performance measurements on an idle machine. The explicit benchmark target is not installed or selected by normal
compiler builds.

Measured locally on 2026-10-13 after indexed trace-location lookup, before stack
argument support (five-sample
medians; synthetic workload above):

| Functions | Mode | Scalar emission | LLVM emission | LLVM/scalar time | Scalar/LLVM runtime |
| ---: | --- | ---: | ---: | ---: | ---: |
| 65 | debug | 0.282 ms | 3.339 ms | 12.1x | 1.00x |
| 65 | release | 0.213 ms | 22.776 ms | 107.0x | 1.52x |
| 257 | debug | 0.410 ms | 8.738 ms | 21.3x | 0.99x |
| 257 | release | 0.309 ms | 77.352 ms | 250.4x | 1.71x |
| 1,025 | debug | 1.072 ms | 32.362 ms | 30.2x | 1.00x |
| 1,025 | release | 0.709 ms | 301.912 ms | 425.9x | 1.68x |

Debug emission previously scanned source from byte zero for every trace label.
The experiment now builds the existing compiler line index once per debug object
and frees it on every exit. Index construction is included in emission timing.
At 1,025 functions, debug emission fell from 19.111 ms to 1.072 ms (17.8x).
All three regenerated debug objects were byte-identical to the previous output.
The earlier report is retained locally as
`build/backend-benchmark-before-location-index.json`.

Lower emission time still trades off against slower release code on this workload.
These measurements exclude frontend preparation and do not establish an
end-to-end compiler speedup.
