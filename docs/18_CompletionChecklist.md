# Dyn Compiler Completion Checklist

This checklist defines what must be true before we call the compiler/toolchain "complete" for v1.0.

Legend:
- [x] done
- [~] in progress
- [ ] not started

## 1) Language Spec Lock

- [x] Create and maintain versioned baseline spec: `docs/spec-v1.md`
- [x] Lock syntax and semantics for all implemented features (current baseline scope)
- [x] Document edge-case behavior (shadowing, coercion, match, visibility, entrypoint)
- [x] Add language versioning note and compatibility expectations

Acceptance criteria:
- A single authoritative spec file exists and is referenced by other docs.
- Every implemented grammar/semantic feature is defined with at least one positive and one negative example.

## 2) Type System Completeness

- [x] Finish/verify type compatibility matrix for implemented primitives and function types (current checker scope)
- [x] Define coercion/inference boundaries in spec and enforce in checker (current numeric/inference rules)
- [x] Add diagnostics for each mismatch class (current checker scope)
- [x] Add regression tests for each mismatch class (core mismatch class coverage added)

Acceptance criteria:
- Type checker behavior matches spec-v1 and tests cover intended and rejected cases.

## 3) Semantic Completeness

- [x] Return-path validation for all control-flow combinations (current language scope)
- [x] Decide and enforce dead/unreachable code policy (current policy: unreachable after break/continue in block)
- [x] Finalize mutability/assignment legality checks (current language scope)
- [x] Validate control-flow legality diagnostics consistency

Acceptance criteria:
- Semantic tests cover if/for/match/labeled/defer combinations and failure diagnostics.

## 4) Backend Correctness and ABI Stability

- [x] Freeze internal call ABI contract (params, returns, calling convention) (`docs/25_ABI.md`)
- [x] Enforce stack alignment and call clobber correctness across generated code (current direct-asm contract)
- [x] Confirm external symbol and cross-module call correctness in multi-object link mode
- [x] Expand ABI mismatch diagnostics and tests

Acceptance criteria:
- Cross-module calls are stable and ABI checks fail with precise diagnostics on mismatch.

## 5) Module and Link Pipeline Robustness

- [x] Harden nested directory module resolution edge cases
- [x] Detect and report duplicate module declaration conflicts cleanly
- [x] Ensure deterministic artifact naming and collision handling
- [x] Expand transitive incremental invalidation tests (rename/delete/move + transitive reverse-dependency tests added)

Acceptance criteria:
- Module graph behavior is deterministic and robust under file graph changes.

## 6) CLI and Build UX Completion

- [x] Core commands: `check`, `build`, `run`, `clean`
- [x] Per-command help output
- [x] `--work-dir` support for build/run/clean
- [x] `run` argument passthrough using `--`
- [x] Add `--json` machine-readable mode for diagnostics and summaries (`check`, `build`, `clean`)
- [x] Finalize and document exit code contract (`docs/19_CLI.md`)
- [x] Add integration tests for CLI flag/arg errors and success flows

Acceptance criteria:
- CLI behavior is predictable, scriptable, and tested.

## 7) Testing and Quality Gates

- [x] Core test suite exists and passes
- [x] Add golden diagnostics tests (stable output snapshots)
- [x] Add CLI integration tests for commands and common failures
- [x] Add end-to-end module build/run fixtures for nested imports

Acceptance criteria:
- CI-style local run validates parser/semantic/backend/CLI e2e flows.

## 8) Reproducible Builds and Caching

- [x] Include all relevant inputs in cache fingerprints
- [x] Verify cache invalidation under transitive edits and file moves
- [x] Document cache behavior and known limitations (`docs/20_Cache.md`)

Acceptance criteria:
- Cache hits and invalidations are deterministic and test-covered.

## 9) Platform Support Policy

- [x] Explicitly state supported targets/platforms for v1.0 (`docs/24_PlatformSupport.md`)
- [x] Emit clear diagnostics for unsupported targets (CLI prints explicit unsupported target/artifact message)
- [x] Add basic target compatibility test coverage for declared support matrix

Acceptance criteria:
- Users know exactly what is supported and unsupported.

## 10) Release Documentation

- [x] Quickstart: install/build/check/build/run/clean (`docs/21_Quickstart.md`)
- [x] Language reference index points to authoritative spec-v1 baseline file exists (`docs/spec-v1.md`)
- [x] Module system guide with directory/module declaration examples (`docs/22_ModulesGuide.md`)
- [x] Known limitations and roadmap beyond v1.0 (`docs/23_KnownLimitations.md`)
- [x] CLI reference and exit codes documented (`docs/19_CLI.md`)

Acceptance criteria:
- New user can install and compile a multi-file program from docs alone.

---

## Execution Order

1. Spec lock and edge-case documentation
2. Type + semantic gap closure
3. Backend/ABI hardening
4. Module/link and cache hardening
5. CLI finalization (`--json`, exit codes, integration tests)
6. Release docs pass
