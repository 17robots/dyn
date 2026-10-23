# Compatibility and support policy

Dyn is pre-1.0. Source and standard-library compatibility may change, but changes must be recorded
in release notes and accompanied by migrations for shipped examples and tests. Core syntax should
be frozen during a release cycle; experimental APIs must not be presented as stable.

Linux x86-64 is the primary target. The [support scope](../internals/release.md#support-scope)
table is the authoritative list of targets and their status. A target leaves
experimental status only after its native release gates record passing results;
configured CI jobs alone are not evidence.
Unsupported names and incomplete executable links are rejected rather than
silently producing partial programs. Stable C interoperation means the documented ABI
for that target, not a cross-platform ABI promise.

Within one release line:

- patch releases fix defects without intentional source breakage;
- minor releases may add APIs and may make announced pre-1.0 corrections;
- removed APIs receive a release-note entry and repository-wide migration;
- debug diagnostics may improve, while release correctness semantics remain unchanged.

Releases should pass the C-compiler test/sanitizer matrix, deterministic clean rebuild checks,
integration projects, and the performance suite. A benchmark regression is evidence to investigate,
not by itself a correctness failure; accepted changes document their cause.
# Validation status

CI gates C bootstrap compiler with ordinary and sanitizer tests, relocated SDK
installation, deterministic release checks, malformed-input smoke tests, application
integration, and informational matched-Clang benchmarks. Benchmark numbers are not
portable pass/fail thresholds across shared CI hardware.

Long-duration production evidence remains maturity work; local validation does not establish it.

The authoritative current scope is [release checklist](../internals/release.md).

## Compatibility boundaries

| Surface | Policy before 1.0 | Required change evidence |
| --- | --- | --- |
| Syntax and semantics | Freeze within a release cycle; reject unsupported syntax consistently in compiler, grammar and editor. | Positive/negative fixtures, debug/release agreement, release note and migrated examples. |
| Public std/vendor APIs | Source compatibility within patch releases; announced pre-1.0 corrections may occur in a minor release. | Updated source contracts, reference generation, migrated repository clients and behavioral regression. |
| `.dynmi` interfaces and caches | Private, disposable implementation artifacts, not distribution formats. | Schema/version validation, epoch bump for semantic incompatibility, stale-cache rejection/rebuild. |
| Dyn objects/shared libraries | Compiler-version and target specific; no development binary ABI promise. | Rebuild every linked Dyn consumer/provider together; ABI probes for lowering changes. |
| C ABI | Selected target ABI for the documented C-compatible subset. | C header layout checks and bidirectional call probes on each target; provider version recorded. |
| LSP/diagnostics | JSON-RPC IDs and protocol shapes preserved; wording may improve. | Cancellation, edit recovery, diagnostic range and completion regressions. |

Serialized interface format has its own version; the frontend/cache epoch is
centralized as `DYN_FRONTEND_VERSION` in `src/dyn.h`. A compiler upgrade
invalidates compiler-keyed object caches too. Never ship `.dynmi` or
cached objects as a stable SDK interchange format.

Every intentional break records old/new usage, affected versions, storage/lifetime
changes and migration tests in release notes. Experimental target support does
not become stable merely because a cross-linked artifact exists.

Upgrade notes for each release are in the [changelog](../../CHANGELOG.md), with
longer guides under [migrations](../migrations/).
