# Large-function performance — 2026-09-21

Fixed the large-function scaling problem identified by the preceding compiler
performance pass. The focused regression gate failed on the original compiler:
four times as many qualified references took roughly sixteen times as long.

Phase timings isolated the dominant cost to module loading. A `-pg` compiler
profile identified repeated `dyn_syntax_local` calls; shared-library execution
time is not fully attributed by that profiler. Semantic analysis of functions
with many locals had a second repeated linear lookup.

## Changes

- Import validation and module qualification share a source-scoped binding index
  in `dyn_scope.h`. It records name/visibility intervals once instead of scanning
  preceding statements for every reference. Sorted names and prefix maximum ends
  support logarithmic existence queries, including disjoint same-name scopes.
- Parameter, variadic, local, constant, loop and case binding visibility preserves
  the previous ancestor-query behavior. Syntax-error recovery retains that query.
  Index names borrow immutable source bytes for one pass; no index is used after
  text rewriting.
- Functions with at least 32 locals use a lazily grown semantic name index.
  Active-name lookup and no-shadowing checks share it. Inactive declarations stay
  indexed for duplicate detection; lookup retains first-declaration order. The
  index is discarded between functions. Small functions allocate no such index.
- Wide child lists in import validation, qualification and block AST lowering use
  cursor traversal. Valid rewrite nodes skip missing-child scans. Missing blocks
  in editor recovery preserve empty-block lowering behavior.

## Measurements

Both compilers use `-O2`; three fresh no-cache checks per workload, same host,
without concurrent builds/tests. Values are median wall milliseconds.

| Workload | Before | After |
| --- | ---: | ---: |
| 1,024 qualified calls | 183.47 | 14.82 |
| 4,096 qualified calls | 2,949.15 | 42.93 |
| 1,024 direct calls | 175.18 | 12.01 |
| 4,096 direct calls | 2,915.35 | 34.11 |
| 1,024 local declarations/uses | 14.34 | 13.26 |
| 4,096 local declarations/uses | 53.68 | 39.31 |

The original 4,096-reference case is about **69× faster**. Quadrupling its size
now takes about 2.9× the wall time instead of 16×. These workloads establish the
specific improvement; they do not prove linear complexity for every language
construct or erroneous input.

[Raw samples, compiler hashes, phase timings and scaling results](large-function-performance-2026-09-21.json)
include the local-heavy semantic timings and broader allocation/RSS/editor gates.

## Validation

- Indexed/ancestor lookup comparison across binding forms, sibling scopes,
  initializers, Unicode comments and recovery trees; index growth allocation
  failures leave no retained partial state.
- Runtime contracts for aliases hidden by parameters, locals, iteration bindings,
  enum payloads and variadics; large local tables reset between functions.
  Duplicate/inactive-local diagnostics retain their original source lines.
- Frontend and module-loading allocation-failure tests now cross both index
  allocation/growth paths. Normal and ASan/UBSan variants passed.
- Compiler contracts/diagnostics, 192 metamorphic builds, incremental cache and
  reflection transitions, constant-array codegen, SDK fixtures and project examples.
- 51 LSP contracts, 66 incremental/fresh comparisons, queued-edit ordering,
  export cache invalidation, grammar/module/interface checks and Neovim completion.
- Separate translation-unit build and static analysis of 26 compiler files,
  with no warnings.
- `benchmarks/large-function.py --verify` and the broader compiler-scaling baseline
  gate passed, including allocation counts, peak RSS and editor latency.

The focused benchmark is now a repeatable scaling gate, so a recurrence of the
quadratic behavior fails without relying on one machine's absolute speed.
No SDK arena API or language semantics changed. No additional platform tests
were run; the existing project validation reported SDL GPU unavailable.
