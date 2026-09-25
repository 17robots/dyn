# Dyn 0.1 release readiness

This is the current release checklist. Historical audits are evidence, not current
feature inventories. The release is a candidate until all required evidence exists.
Tests demonstrate particular contracts; they do not prove absence of all defects.

Run the complete local candidate gate with `just release-check`. See
[validation and publication workflow](validation.md) for dependencies, reports,
native runners, performance baselines, and remaining external evidence.

## Release scope

| Surface | 0.1 policy | Evidence required |
| --- | --- | --- |
| C compiler host | Linux x86-64 | GCC/Clang build, sanitizers, install/relocation, packaged SDK |
| Linux x86-64 output | Primary release target | Compiler/runtime/SDK, FFI, concurrency and application gates |
| Linux AArch64 output | Experimental until native gates pass | Native runtime, ABI, arena and concurrency probes |
| Windows x86-64 output | Experimental until native gates pass | Native runtime, ABI, arena, filesystem/socket/process probes |
| macOS AArch64 output | Experimental until native gates pass | Native runtime, ABI, arena, filesystem/socket/process probes |
| Compiler on Windows/macOS | Not promised | POSIX host implementation is not a portable-host claim |
| Browser Wasm / WASI Preview 1 | Experimental modules / commands | JS engine imports/exports, memory and ABI probes; browser UI qualification remains separate |
| Core syntax | Frozen for 0.1 | `docs/language.md`, conformance inventory, positive/negative tests |
| Core SDK | Candidate APIs | Documented ownership/failure contracts and fixture gates |
| Linux thread/sync | Candidate low-level APIs | Contention, wakeup, lifecycle and native architecture tests |
| Native providers | Optional, version-qualified | Version report plus ABI/behavior contracts on each supported environment |
| GPU/driver surfaces | Experimental | Actual hardware/driver execution, not semantic checks |
| Crypto/TLS production assurance | No independent-audit claim | Known-answer/malformed-input tests plus external review for stronger claims |
| LSP/Neovim | Candidate | Protocol, incremental/fresh equivalence, large workspace and soak checks |
| Published Zed extension | Pending publication verification | Exact upstream grammar pin, installed extension test |

Dyn-owned heap storage uses `std/mem` arenas. Buffers may be stack-backed or
arena-backed. Pools/free lists remain in `std/mem`. Native provider allocations
follow provider lifetime contracts. No `owned`, `growing`, or `take` package is
required. Self-hosting, generics, package registries and new ownership syntax are
outside the 0.1 release work.

## Acceptance inventory

| ID | Work | Acceptance/evidence |
| --- | --- | --- |
| R01 | Scope and support matrix | This document; experimental targets not advertised as validated |
| R02 | Reproducibility and installation | `tests/reproducible-builds.py`, `tests/install-sdk.sh`, packaged SDK test |
| R03 | CI and performance gates | Shared pinned setup; compiler/sanitizer, SDK, scaling and scheduled jobs |
| R04 | Native target evidence | Expanded probes execute on native runners; a cross-link is insufficient |
| R05 | Specification coverage | `conformance.json`; reviewed rules map to executable positive/negative/runtime tests |
| R06 | Robustness | Fuzz, fault injection, resource limits, malformed input, failed builds and recovery |
| R07 | LSP scale and lifetime | Multi-root/open/close/edit cycles; current diagnostics, bounded memory and latency |
| R08 | Editor distribution | Remote grammar comparison and release handoff; no automatic publication |
| R09 | Arena and retained-result contracts | `memory.md`, `buffer-contracts.md`, lifetime and boundary tests |
| R10 | SDK public API coverage | Generated API-reference inventory; per-package fixtures; references are not proof of behavior |
| R11 | Protocol/format scope | `formats.md`; supported subsets and explicit failure cases |
| R12 | Provider compatibility | Build/test within each baseline; versions and ABI logs retained |
| R13 | Concurrency | Multi-worker contention, condition predicate, semaphore and once tests |
| R14 | Performance | Existing scaling gates plus long-session/soak metrics; no check weakening |
| R15 | Documentation | Keep current claims consistent; preserve reproducible validation evidence |
| R16 | Packaging/versioning | Manifest, hashes, dependency policy, unpacked SDK smoke and release notes |
| R17 | Application/security evidence | Bounded soak report; longer/external evidence remains honestly pending |
| R18 | Feature freeze | No new syntax or self-hosting as a substitute for validation |

Local results are recorded under `build/readiness`; release workflows retain
JSON reports and artifact checksums. CI configuration is not evidence that CI ran. Native
runner execution, actual GPU coverage, publication, independent security review,
and sustained user experience must be recorded separately before stronger claims.

## Toolchain and compatibility

The release CI baseline is LLVM/Clang 19, Tree-sitter runtime/generator 0.25.8,
and Zig 0.16.0 for cross-linking. Local LLVM 22 validation is additional evidence,
not a replacement for the pinned baseline. Linux packages currently use system
shared LLVM/Tree-sitter dependencies; they are not standalone binaries. Package
manifests record actual linked dependencies. Do not label a local LLVM 22 package
as the LLVM 19 release artifact.

Within the 0.1 line, syntax changes require a reviewed decision, conformance and
editor updates, migration notes, and refreshed generated grammar. Stable API
removals require migrations of shipped examples. Unsupported forms remain
rejected, including generic struct literals and local aliases.

## Follow-up gates

`just test-followups` checks aggregate ABI, semantic combinations, analysis work
budgets/cancellation/recovery, binding reports/layouts, SDK behavior and generated
reference freshness. Sanitizer runs include the compiler-facing probes. CI builds
aggregate probes for native target runners; local cross-link status remains
separate from native execution. See [validation](validation.md),
[SDK reference](../reference/README.md), [behavior inventory](sdk-behavior.json),
and [compatibility/migrations](../stability.md).
