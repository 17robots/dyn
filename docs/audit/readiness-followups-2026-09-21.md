# Readiness follow-ups — 2026-09-21

All seven follow-up areas have local implementations and regression gates. Dyn
remains a development candidate. Native CI execution, complete behavioral API
coverage, hardware validation and independent assurance are not implied.
[Machine-readable results](readiness-followups-2026-09-21.json) identify the compiler
binary and retained logs. This supersedes the aggregate restriction and reference
counts in the earlier [readiness audit](release-readiness-2026-09-21.md).

## Changes

1. **Target aggregate ABI.** One shared lowering plan handles declarations,
   parameters, direct/indirect calls, results and callbacks. It implements SysV
   eightbyte/register-pressure rules, Windows x64 record coercion/indirection,
   and AArch64 small records/homogeneous floating aggregates. Padded coercion
   storage avoids reading beyond small logical records. Dyn-only foreign types
   remain rejected. Sixteen struct shapes pass against GCC and Clang in both
   build modes; Windows/macOS/AArch64 probes cross-link and are wired into native
   CI. Full arbitrary C type/declarator support is outside the documented subset.
2. **Semantic combinations.** Thirty-two alias/import/constant/cast/callback/defer
   combinations cover debug/release and cached/uncached builds. Eight negative
   check/build cases remain rejected. Constant-expression validation is iterative,
   accepts numeric casts, and resolves all globals before following forward
   constant references. Forward field defaults and long arithmetic expressions
   pass. Dyn caller cleanup now runs when C invokes a panicking Dyn callback.
3. **SDK behavior.** Inventory-guided cases cover arena uninitialized allocation,
   overflow rollback, pool exhaustion/reuse, JSON constructors/membership/borrowing,
   bounded partial I/O and borrowed string views. A reproduced duplicate JSON
   attachment made a node point to itself; parent tracking now rejects duplicates,
   cycles and reparenting without mutation. Heap allocation remains arena-based.
   The reference inventory now has 701 direct textual references among 1294
   declarations; this is navigation data, not a behavioral coverage percentage.
4. **Bounded analysis.** CLI `--max-work`, LSP work/CPU limits and JSON-RPC
   cancellation share cooperative checkpoints. Parsing, lowering, semantics,
   module loading and editor declaration scans participate. Interrupted semantic
   and export results are not cached. Tests sweep budgets through compiler stages,
   cancel numeric/string IDs (including escaped strings), deliver cancellation
   during dependency parsing, and verify recovery. Deep module/initializer graphs
   produce explicit bounded-depth diagnostics instead of exhausting the C stack.
5. **Binding tooling.** Supported struct declarations can appear by value.
   `--report` records known omissions and uninterpreted preprocessor directives.
   `--verify-layout TARGET` builds a C/Dyn size/alignment/field-offset oracle;
   `--run-layout` executes it. A deliberately mismatched packing pragma fails.
   Cross-link-only reports never claim runtime verification. The conservative
   text frontend remains explicit about incomplete header coverage; no unneeded
   second Clang frontend was introduced.
6. **SDK reference.** `dyn docs` now includes adjacent source contracts, source
   links and target gates, and fails on invalid syntax. Generated pages cover 89
   packages, with signatures, lifetime/failure notes and executable fixture links.
   Missing contract review is marked explicitly. Source comments and the reviewed
   behavior inventory remain the sources; `--check` detects stale pages.
7. **Compatibility.** Policies distinguish source syntax, public APIs, disposable
   interfaces/caches, compiler-specific Dyn binaries, C ABI and LSP. Frontend/cache
   epoch 5 is centralized. Migration examples require rebuilding aggregate ABI
   consumers and creating separate JSON nodes for separate parents. `Value` size
   changed; callers must use `#sizeof`/`#alignof` rather than hard-coded storage.

## Validation

- `make quality-c`: normal tests, editor/grammar/module checks, allocation-failure
  injection, ASan/UBSan, fuzzing and all 26 C static-analysis units pass.
- `make test-libraries`, `projects/validate.sh`, `make test-readiness`,
  `make install-check` and `tests/release-gate.sh` pass.
- Aggregate probes execute on Linux x86-64 with GCC and Clang, debug/release;
  Windows x64, macOS AArch64 and Linux AArch64 debug/release probes cross-link.
- Twelve clean release builds remain byte-identical. Current bounded soak passes
  120 runtime executions plus twelve 64-document workspace cycles.
- Wide-function, member/debug-local, compiler scaling/allocation/editor and warm
  cache gates pass. Warm compilation median is 4.87 ms versus 9.10 ms cold on this
  host. Editor median is about 4.82 ms versus 4.40 ms in the prior local snapshot;
  the added checks are not presented as a speedup. Matched-Clang runtime samples
  meet existing compute/arena/format/I/O ratio budgets.
- Source/reference freshness and binding layout/report checks pass. SDK packaging
  includes these documents and validates the unpacked, relocated installation.

Reproduce core additions with `make test-followups`. See [FFI](../ffi.md),
[SDK reference](../reference/README.md), [behavior inventory](../release/sdk-behavior.json),
and [compatibility/migrations](../stability.md).

## Remaining evidence

Native target execution and pinned LLVM 18/provider CI must run on their actual
runners. Published editor grammar/pins, GPU/hardware behavior, sustained production
use and independent security review remain external work. The binding frontend is
not a complete C parser. Per-function documentation/behavior gaps remain visible
in the generated reference. Budgets are cooperative and do not interrupt blocking
filesystem calls. Passing this batch does not prove the language bug-free or ready
for an unconditional stability promise.
