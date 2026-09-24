# Dyn bootstrap compiler

## Bootstrap architecture

Dyn uses a thin vertical slice from source to native executable:

```text
module directory -> source manager -> Tree-sitter -> owned AST -> semantic checks
                 -> typed IR -> LLVM C ABI -> ELF object -> linker -> executable
```

Executable targets are `x86_64-linux`, `aarch64-linux`, `aarch64-macos`, and
`x86_64-windows`. Cross-linking macOS uses `zig` (its bundled Mach-O linker),
while Windows uses GNU `ld`'s `i386pep` backend; neither output is executed by
the Linux test host. `--no-link` emits Mach-O arm64 and COFF x64 objects.
Cross-target smoke programs also compile and link `std/os/windows` and `std/os/macos`: Windows x64
provides Win32 file/page-memory/thread, Winsock socket, and `WSAPoll` adapters;
macOS arm64 provides Darwin file/page-memory/socket/poll adapters. The macOS
bootstrap does not claim native thread creation yet (`has_native_threads` is
false). These artifacts are format- and unresolved-symbol-checked on Linux,
not executed; native-host CI remains required for behavioral certification.
`--target` rejects every other value before code generation. Backend
uses that explicit triple rather than host default, so cross-host execution
cannot silently produce an object for the wrong architecture. Runtime object,
syscall ABI, ELF linker policy, and dynamic-loader path remain target-specific;
other targets require their own runtime/platform implementation. Linux AArch64
emits native ELF objects; execution tests require AArch64 hardware or an external
emulator. `#syscall` uses portable Linux IDs (matching x86-64); constant IDs with
argument-compatible AArch64 calls are translated during checking. Dynamic or
unmapped IDs are rejected, preventing x86-64-only calls from silently
using wrong kernel operations.

Target identity and capabilities (`arch`, `kernel`, ABI, libc boundary,
endianness, and pointer width) live in one compiler descriptor. Both `--target`
and `#target` consume it. Only targets supplying tested startup runtime, linker
policy, ABI layouts, and platform stdlib are executable targets.

The implemented front end covers functions, primitives, locals, control flow, structs,
pointers, arrays/slices, enums/case, and the first module/import slice. Integer arithmetic,
division, shifts, pointer access, indexing, and slicing retain runtime safety checks in debug
and release. Bare expressions are not statements; calls receive dedicated statement handling.

Control flow uses compiler-owned statement trees referencing child-statement ID lists. Semantic
analysis enforces boolean conditions, block visibility, forbidden shadowing, valid loop exits,
and unreachable statements. LLVM lowering emits explicit basic blocks for `if`/`else`, condition
or infinite `for`, `break`, `continue`, and returns nested in branches.

Struct declarations become nominal type IDs with ordered field tables and compiler-calculated
size/alignment. Packed structs remove field padding and use alignment 1. LLVM uses named aggregate
types, `insertvalue` construction/update, and `extractvalue` access. Struct locals and assignments
copy aggregate values. Same-directory files share one deterministic declaration namespace.

General-function lowering collects all signatures before any body, then resolves typed calls,
parameters, returns, forward references, and recursion. Each function owns its local-ID range.
LLVM functions are declared as one batch before bodies are emitted.

## Modules

The module loader canonicalizes directory imports, forbids project-root escape, recursively loads
dependencies, and reports complete import cycles. Imports bind an optional alias; imported
functions, structs, and enums require qualified access and `pub`. Qualified function calls,
struct types/literals, enum variants, and payload patterns pass through semantic analysis and
native code generation. Compiler-owned source copies receive stable internal symbols derived from
their canonical module paths before AST construction. Different modules may therefore declare
identical function, struct, and enum names without collisions.
Input limits are explicit: 64 MiB per source, 4096 source files per module, and 256 MiB after
module merge. Oversized input fails before its source buffer is allocated.

## Typed Dyn IR

Typed IR is a deep module at the semantic/backend seam. Its small interface accepts one checked
AST and returns one self-contained `DynIrProgram`; destruction is the only other operation.
Lowering strips source-only names and spans, copies resolved type/local/function/field IDs, and
normalizes compound assignments into ordinary typed expressions. Validation rejects unresolved
types, invalid IDs, malformed child ranges, and non-normalized assignments before LLVM runs.

LLVM lowering consumes only typed IR. Semantic AST is freed before LLVM context creation. This
keeps source-language knowledge local to parsing/sema and backend knowledge local to codegen.

## Globals and initialization

Top-level ordinary variable declarations create mutable zero-initialized storage. Explicit and
inferred types, reads, writes, compound assignments, addressable aggregate access, and imported
`pub` globals flow through AST, semantic analysis, typed IR, and LLVM. `const` declarations require
compiler-evaluable initializers and reject writes. A generated `dyn_init` function evaluates
runtime initializers once before `main`; imported module sources are ordered before importers.
The semantic pass follows direct references and global reads reachable through called functions,
topologically orders initialization, and rejects cycles. Compiler-evaluable scalar, struct, and
array constants are emitted directly as read-only LLVM globals. Runtime work is split into stable
per-module `__dyn_init_*` functions, emitted only for modules that need it and called dependency-first.

Function signatures are structurally interned independently from pointer descriptors. Semantic
analysis resolves `&function`, checks indirect argument/result types, and preserves signature IDs
in typed IR. LLVM lowering emits opaque function-pointer values and typed `call` instructions;
every indirect call receives a non-null guard. Function addresses also participate in static
constant aggregate initialization.

Pointer types are interned nominal descriptors containing pointee type and shallow-const flag.
Typed IR preserves those descriptors while dropping source syntax. Backend lvalue lowering handles
locals, explicit dereference, nested fields, packed fields, and automatic pointer-field access
through one storage-pointer path. Dereference guards validate non-null and pointee alignment before
loads, stores, or field address calculation; guards remain in release builds.

Array and slice types are interned descriptors carried through typed IR. LLVM lowers fixed arrays
to native array aggregates and slices to `{ptr, i64}` values. One indexed lvalue path handles loads,
stores, address-taking, and compound assignments with runtime bounds guards. Range lowering checks
`start <= end <= len`; `for-in` evaluates its collection once and copies each element into the
iteration binding. Pointer iteration bindings remain a later extension.

Enum lowering records nominal variants, backing tag type, maximum payload size/alignment, and final
tagged-union layout. Case analysis normalizes literal/range patterns into disjoint closed intervals,
checks full-domain or variant coverage, and emits branch chains. `_` is always the fallback,
independent of source-arm order.

Defer lowering maintains a lexical cleanup stack during control-flow emission. Block fallthrough,
`return`, `break`, `continue`, explicit `#panic`, and generated safety guards emit active cleanups in
reverse order. Deferred-call operands are evaluated into hidden slots at the defer site; deferred
blocks instead load live local storage at exit. Cleanup code suppresses recursive cleanup if it
panics. Panic checkpoints around calls propagate cleanup through caller frames without allocation;
a second panic aborts remaining cleanup.

Builtin expressions lower directly into typed IR. `#sizeof` and `#alignof` use compiler-owned
layout descriptors and never evaluate value operands. `#cast` emits explicit LLVM numeric or
pointer conversions; `#bitcast` requires equal compatible scalar representations. Linux x86-64
`#syscall` accepts a syscall number plus up to six integer/pointer arguments and calls a tiny
libc-free register-shuffling runtime bridge. `#typeof` resolves operand types without evaluation,
materializes compiler-owned `TypeInfo`, and lowers only used type-name metadata into IR.

Compiler data uses integer IDs into arena-backed arrays. Long-lived source, module, AST,
type, and IR data use a persistent arena. Temporary phase data uses a resettable scratch
arena. The present source loader still uses libc allocation; replacing that with these
arenas is next implementation slice.

Linux x86-64 starts without libc: `dynrt_start.o` defines `_start`, calls generated
`main`, then performs exit syscall. LLVM emits native objects. Linker selection prefers
bundled `ld.lld` in SDK; development fallback currently uses system `ld`.

Standard-library imports resolve relative to compiler executable, never process working
directory. Initial `std/terminal` and `std/io` are ordinary Dyn over `{data,len}` UTF-8 strings and `#syscall`;
its ABI is documented in `standard-library-abi.md`.

Root justfile defaults to unity compilation. `just per-file` validates module boundaries.
Generated Tree-sitter parser files remain committed; `just grammar` regenerates them.
`just test-c` excludes deferred self-host tests. `just sanitize-test-c` runs that
same C-compiler suite under ASan/UBSan; `just quality-c` runs per-file build,
ordinary C suite, then sanitizer suite.

`just fuzz-c` adds deterministic generated parser/checker inputs and a generated
runtime arithmetic program. Run `tests/fuzz-smoke.sh` with sanitized `DYN` to
exercise generated binding and debug/release differential corpora as well. Seed control,
failure preservation, and regression-minimization policy are in [fuzzing](fuzzing.md).
detect compiler memory and undefined-behavior faults. Cases reproduce by index.

`--timings` prints load, check, codegen, and link wall time to stderr. `just install`
installs compiler, runtime objects, and standard library under `PREFIX`; `just
install-check` validates a relocated SDK outside source tree. Both Linux targets
ship startup/support objects; target seam remains explicit, not a portability claim.
Cross-linking AArch64 Linux executables uses `ld.lld` or Zig's bundled `ld.lld`;
compiler never feeds AArch64 objects to host `ld`. Object and assembly emission
need only LLVM backend. Tests execute through `qemu-aarch64` when available.

## Error boundaries

CLI/environment failures exit 2. Source diagnostics exit 1. Success exits 0. Parser and
semantic passes collect up to 20 reliable errors. Internal assertions never substitute
for user diagnostics.

## Build modes

Debug is default (`O0`). Release gives non-entry definitions internal linkage, runs LLVM's
`default<O2>` pipeline, and removes unreachable whole-program code. Language safety checks remain
enabled in both; release may eliminate a check only when LLVM proves it cannot fail.
Checked add, subtract, and multiply use LLVM overflow intrinsics, preserving traps while exposing
their semantics to optimization passes.
Code generation reuses exact nil/alignment and index facts while the successful guard block
dominates the use. Facts key on LLVM SSA values: an intervening load after any possible aliasing
store is a different value. A branch merge only retains a fact when every incoming path passed its
guard. This small CFG proof is sound in debug builds too; LLVM performs broader dominance/range
optimization in release builds.
Repeated loads from one local slot are equivalent only inside one source statement, where no
intervening statement or call can mutate the slot.
Typed IR performs conservative unsigned loop-range proofs. It removes checked additions only when
an exact induction bound and maximum accumulated value prove overflow impossible, and array bounds
checks only when the inferred unsigned index maximum is below the fixed array length. Nested
control, defer, calls, unknown stores, and possible local aliases invalidate the proof.

`dyn run DIR` builds a temporary executable, runs it without shell mediation, returns its exit
status, and removes the executable. `--no-link` is rejected for `run`. `--emit-asm` writes the
post-optimization target assembly beside other requested build artifacts.
Build output is created through a temporary sibling and atomically renamed.
On x86-64 Linux release builds, separately compiled modules use ThinLTO bitcode
when a version-compatible `ld.lld` is available; otherwise the compiler emits
cached native objects and falls back to the system linker. Debug builds always
use native objects. Zig's bundled linker is not selected because its LLVM major
may differ from the compiler's bitcode producer.

Plain executable builds use a content cache beside output. A versioned input snapshot validates
compiler, target, mode, output, link inputs, module directories, manifests, and transitive sources
before frontend loading. Unchanged builds therefore skip discovery, parsing, code generation, and
linking. Metadata uncertainty falls back to content validation; `--no-cache` forces rebuilding.
Runs and artifact-emitting builds bypass executable cache.

`dyn build MODULE --shared --output libname.so` emits a position-independent
ELF shared library on Linux x86-64 or AArch64, a PE DLL on Windows x86-64, or
a Mach-O dylib on macOS AArch64. Public functions and globals are
exported with their Dyn names; private declarations are hidden. The library
contains Dyn's runtime support but no executable startup object. Shared-library
builds bypass the executable cache and cannot be combined with `run` or
`--no-link`. The Linux gate executes a native ELF consumer. It cross-links PE
and Mach-O consumers and inspects their export/import metadata, but does not
execute them; native Windows/macOS CI is still required for runtime validation.
Windows DLL output also writes the GNU-compatible sibling import library
`OUTPUT.a`, which is the link input for cross-target Dyn consumers.

## Tooling and projects

`dyn fmt DIR` performs conservative, semantics-preserving canonicalization: CRLF becomes LF,
trailing horizontal whitespace is removed, and non-empty files end in LF. It validates source
before atomic replacement and preserves file permissions. `dyn fmt --check DIR` changes nothing
and exits 1 when formatting differs.

`dyn docs DIR` emits Markdown containing public declarations. `dyn lsp` implements bounded
JSON-RPC framing, lifecycle, incremental document synchronization and tree reuse, compiler-backed
diagnostics, hover, completion/snippets, signature help, references, rename, formatting, symbols,
semantic tokens, inferred-type and call-parameter inlay hints, document highlights, folding ranges, selection ranges,
semantic incoming/outgoing call hierarchy,
rename preparation, and cross-document definition.
Open-document storage grows dynamically; each decoded text is limited to 1 MiB and URIs to 64 KiB.
The server performs no filesystem mutation. Typed hover and local/global/field definition lookup query the resolved compiler
AST, so inferred variables report their concrete type. Struct and enum hover summarize members;
function completion includes signatures and positional-argument snippets. Struct literals, enum
variants, typed enum assignments, call arguments, return expressions, locals, loop bindings, and result fields receive
type-directed completion. Results are deduplicated, locals sort before declarations, and unrelated
open packages do not leak private or unqualified public declarations. Imports support
unused-use warnings and quick fixes, nested path/member completion, imported hover, filesystem navigation,
qualified auto-import edits, and unknown-symbol quick fixes that insert `use` and qualify the symbol.
Struct literals offer a rewrite action that inserts absent fields with type-appropriate defaults.
Type-definition navigation follows inferred struct and enum values;
declaration and implementation navigation resolve concrete Dyn declarations.
References and rename use compiler bindings and merged-source origin maps. Functions, locals, globals,
and fields remain distinct even when names match; same-package unopened files and imported package
sources participate without requiring editor buffers. Rewrite origin maps translate qualified imported
members back to their original source positions.
Workspace-symbol queries include unopened files from the workspace root, with open buffers overriding
disk contents. Watched-file, workspace-folder, and configuration changes refresh diagnostics. Merged
compiler sources retain origin maps so diagnostics and navigation report original paths and ranges.

`--diagnostics json` emits source diagnostics as newline-delimited JSON objects with severity,
message, path, and 1-based start/end range. Human diagnostics remain default.

Optional `dyn.project` grants imports access to explicit dependency roots:

```text
dependency utility ../utility
```

`use "utility/submodule"` then resolves below that canonical root. Duplicate names, malformed
lines, missing directories, and traversal outside a declared root are rejected. Without a
manifest, imports remain confined to project root plus `std`.
Compiler emits one object per module for ordinary executable builds. `--jobs N` bounds process
workers; zero defaults to available CPUs. Every worker owns its LLVM context. Dependency symbols are
declarations, owned symbols and module initialization are definitions, and root calls initialization
in deterministic dependency order. Completion order never affects output ordering.

Module objects and interfaces use shared content-addressed storage (`DYN_CACHE_DIR`, then the
platform user cache directory) keyed by compiler bytes, target, mode, module
implementation, and declarations in the module's transitive import dependencies.
Private function-body changes rebuild only their module; declaration changes rebuild
affected importers while retaining unrelated objects. Private types/constants are
included conservatively because public declarations can expose them. Projects using
reflection retain project-wide content dependencies for stable type metadata. Explicit link-input
changes relink without rerunning LLVM. Stored object digests are verified; corruption becomes a miss.
Artifact-emitting and `run` builds retain monolithic codegen because they have different output and
lifetime contracts.
`dyn cache stats` reports shared-cache use; `dyn cache clean` removes shared artifacts.


`dyn docs MODULE_DIRECTORY --json` exports schema-versioned public declarations,
source comments/locations and parsed target gates without an LSP server. It uses
syntax parsing, not semantic validation; private declarations and function bodies
are omitted. See [agent workflow](agent-guide.md) for query examples and limitations.
