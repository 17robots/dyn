# Dyn design and standard-library completion plan

The target is not feature count. It is a small language whose modules provide
high leverage, visible costs, explicit ownership, and predictable native code.

## Design invariants

1. One language construct per idea; additions must delete more complexity than
   they introduce.
2. No hidden allocation. Interfaces receiving storage accept a slice or arena.
3. Values have ordinary value semantics; pointers and slices are explicitly
   borrowed and never extend storage lifetime.
4. `any` is `{type, data}` with type cases as its sole safe inspection construct.
5. Integer overflow, invalid shifts, bounds, nil dereference, and bad alignment
   are checked unless the compiler proves the operation safe.
6. Release optimization may remove diagnostics, never correctness checks.
7. C interoperation lives in `std/c`; `rawptr` is the untyped-pointer escape hatch.
8. Strings are byte slices. UTF-8 operations use `u8` input and `u32` code points.
9. Errors are normal values, not a compulsory language mechanism.
10. Debug/release differences and operation costs are specified and tested.

## Error results

Dyn does not prescribe one universal result type:

- return `bool` when callers only need success/failure;
- return a sentinel only when every value outside it is unambiguous;
- return a struct for a value plus orthogonal status/error information;
- return an enum when callers must exhaustively distinguish failure kinds;
- panic only for violated invariants or operations explicitly documented as
  infallible convenience forms.

The standard library should normally pair expected-failure and infallible forms,
such as `arena_try_push` and `arena_push`. User programs remain free to model
errors differently.

## Arena safety model

Arenas prevent per-object double-free and most leak classes because individual
objects are not freed. They make ownership visible at the interface and make
bulk cleanup deterministic. They do not detect a pointer or slice used after
`rewind`, `reset`, sub-arena destruction, or parent release. Documentation and
tests must state that every borrow dies at those operations. Future static
lifetime checking is optional; it must not complicate ordinary arena use.

## Milestones

### M1 — specification and compiler consistency

- Specify lexical grammar, types, conversions, overflow, case exhaustiveness,
  enums, `any`, variadics, memory, module initialization, C ABI, and targets.
- Add conformance and negative tests for every rule.
- Keep syntax frozen for one release cycle.
- Make empty fixed-array initialization constant-size IR and benchmark compile
  time at 1 KiB, 1 MiB, and 64 MiB.
- Bound parser/sema/codegen time by syntax and explicit initializer count, not
  by an empty array's storage size.

Exit: specification matches implementation; large empty arrays compile without
size-dependent IR growth.

### M2 — predictable performance

- Differential benchmarks against matched Clang for calls, arithmetic, slices,
  structs, payload enums, type cases, typed variadics, `...any`, and syscalls.
- Teach range analysis to remove loop-proven overflow/bounds checks.
- Remove redundant nil/alignment checks after domination proves them once.
- Bring arena push/reset/zeroing near matched C without weakening semantics.
- Split debug tracing and unused runtime routines from release images.
- Add benchmark history and explicit regression tolerances.

Exit: idiomatic Dyn is normally within 10% of matched Clang; larger gaps have a
documented safety or algorithmic cause.

### M3 — foundation packages

- `mem`: arenas, sub-arenas, two-scratch selection, pools/free lists, copy,
  move, compare, zero, endian helpers, checked capacity arithmetic.
- `str`: byte searching/splitting/joining, parsing, ASCII, UTF-8 validation and
  `u32` decode/encode, arena-backed construction.
- `fmt`: integer bases, correct round-trippable floats, escaping, typed and
  `...any` formatting into caller storage; no writer hierarchy.
- `io`: descriptor read/write, explicit caller-backed buffered reader/writer,
  line/byte scanning, copying, and explicit flushing.

Exit: each module has a small procedural interface, ownership/cost docs,
capacity-failure tests, fuzz tests, and two real callers.

### M4 — OS and applications

- `os`: files, metadata, directories, environment, process/spawn/wait/pipes,
  mmap, signals, clocks, terminal queries.
- `path`: clean/join/split/ext/absolute/relative with target-aware rules.
- `net`: addresses, TCP/UDP, polling, nonblocking mode, timeouts, DNS.
- `cli`: caller-arena parsing, subcommands, generated usage text.
- `testing`: assertions, temporary resources, subprocess tests, benchmarks.

Exit: recursive search, process supervisor, and interactive terminal projects
use only standard modules and direct domain code.

### M5 — data and interoperability

- JSON tokenizer/parser/writer with precise errors and caller-owned storage.
- Base64, stable non-cryptographic hashes, checksums, binary/endian helpers.
- Validate `std/c` against libc-free calls, libc, SQLite, and one graphics or
  windowing library; document ownership and variadic ABI restrictions.
- HTTP/1 request/response parsing and a small client/server over `net`.

Exit: JSON CLI, HTTP file server/client, archive inspector, and SQLite project
pass deterministic integration and malformed-input tests.

### M6 — maturity gate

- Parser, checker, formatter, JSON, UTF-8, paths, CLI, and protocol fuzzing.
- GCC/Clang ASan+UBSan for the C compiler; debug/release test matrices.
- Deterministic clean builds, supported-target CI, release notes, versioning,
  compatibility policy, and ABI policy.
- Cookbook, memory guide, cost table, C guide, and package reference.
- Soak-test real applications and preserve every discovered bug as a regression.

Exit: no known correctness defects in supported workflows, stable core syntax,
reproducible releases, and sustained real-world use.

## Change gate

Every language or standard-module addition must answer:

1. What caller complexity disappears?
2. Is this a deep module or merely a pass-through?
3. Are allocation, ownership, errors, and performance visible?
4. Can existing constructs express it clearly?
5. Which conformance, negative, fuzz, integration, and benchmark tests prove it?
