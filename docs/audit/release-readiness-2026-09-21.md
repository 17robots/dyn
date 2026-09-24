# Release-readiness work — 2026-09-21

Historical first readiness batch. Aggregate-ABI restrictions and API-reference counts below
are superseded by [the follow-up audit](readiness-followups-2026-09-21.md).

Dyn remains a **0.1 development candidate**. The local implementation, regression,
packaging and validation work below is complete; native CI execution, publication,
hardware coverage and independent assurance are not fabricated as local results.
The authoritative scope is [release readiness](../release/readiness.md).

## Bugs fixed

1. **Compiler stack overflow:** 8192 nested groups crashed with SIGSEGV. A shared
   iterative Tree-sitter depth guard rejects trees over 1024 levels before recursive
   consumers. Compiler text/JSON diagnostics and LSP recovery are tested, including
   malformed trees and later valid edits.
2. **Mandatory cache writes:** `--no-cache` still wrote/read `.dynmi` files and failed
   with an unusable cache directory. Module interfaces now remain owned in memory;
   cache load/store is optional. Uncached builds create no cache artifacts, and
   ordinary builds tolerate unavailable cache storage. Existing incremental reuse
   and invalidation tests still pass.
3. **Aggregate C ABI miscompilation:** a three-word struct passed to C returned the
   wrong result in debug/release. Unsupported by-value foreign aggregate boundaries
   now produce a compile-time diagnostic. Existing FFI tests use explicit C pointer
   adapters; Dyn aggregate calls remain valid. This restricts an unsafe feature;
   it does not implement a C ABI classifier.
4. **Binding generation:** C `long` incorrectly used pointer width on Windows;
   integer enum expressions could raise an uncaught exception; C octal values were
   mishandled; a `(void)` callback parameter list generated a bogus parameter.
   Target-aware aliases, checked literal parsing and empty callback lists fix these.
5. **Nested build directories:** generated unity includes assumed exactly one path
   component below the repository. They now resolve from an explicit source-root
   include path. A separate nested Clang build verifies the fix.

## Scope completed locally

| IDs | Work and result |
| --- | --- |
| R01, R18 | 0.1 support matrix, syntax/API freeze, self-hosting deferred |
| R02 | 12 uncached builds across worker counts/cwd/output names produce identical executable bytes; installed SDK relocation passes |
| R03, R14 | Pinned shared CI setup, scheduled sanitizer fuzz/soak, native/provider jobs, compiler scaling/allocation/editor gates |
| R04 | Linux x86-64 ABI/storage/callback/arena execution; AArch64 Linux, Windows and macOS probes cross-link; native jobs prepared |
| R05 | 18 rule families map to 65 executable positive/negative fixtures and dedicated runtime/editor tests |
| R06 | Nesting/malformed input, output/cache failures, allocation fault tests and sanitizer differential fuzz |
| R07 | 64 open documents across two roots, 250 edit/recovery/close/reopen cycles, RSS and latency samples |
| R08 | Local grammar corpus/regeneration/provenance verified; stale remote pin measured; hashed publication bundle prepared |
| R09 | Arena-only policy and retained-result contracts preserved; lifetime/storage/buffer tests rerun |
| R10 | Public SDK reference inventory: 1294 declarations, 680 with direct textual test references; existing SDK behavior/property/provider suites rerun |
| R11 | Format/protocol limits consolidated without adding speculative features |
| R12 | Local OpenSSL 3.6.4, SQLite 3.53.4, zstd 1.5.7 debug/release probes pass; CI compiles on each provider baseline |
| R13 | Four-worker mutex/condition/semaphore/once/atomic/join contention probe passes debug/release and soak |
| R15 | Stale document-cap, FFI, generator, collection and self-hosting claims reconciled |
| R16 | Candidate SDK manifest/checksum, unpacked relocation smoke, release notes and handoff prepared |
| R17 | 2500 runtime executions plus editor churn; concrete compiler-boundary review and security evidence documented |

The public API index is deliberately not labeled behavioral coverage. It can have
textual false positives and omits generated/transitive tests. The conformance index
covers rule families, not every language rule or compiler branch. Neither count
justifies claiming every bug or API edge case has been found.

## Validation

- `make quality-c`: normal/compiler/editor/fault tests, ASan/UBSan, fuzz and Clang
  analysis of all 26 compiler translation units pass; no analyzer warnings.
- New robustness and foreign-boundary regressions pass under ASan/UBSan.
- Additional sanitizer fuzz: seed 731, 1000 smoke cases; frontend differential
  fuzz: seed 731, 520 versions across compiler check/build and incremental/fresh LSP.
- `make test-libraries`, `projects/validate.sh`, `make install-check`, binding
  generator tests and `make test-readiness` pass. Project validation checks 110
  SDK/project modules and runs shipped applications.
- Linux native scalar/callback/storage ABI, provider debug/release tests and
  cross-target probe links pass. SDL 3.4.16 layout/callback tests pass. Vulkan
  development headers were absent in this run; the loader alone is not layout or
  hardware evidence. SDL GPU execution reported unavailable.
- Large-function, member/debug-local, compile-scale and compile/runtime benchmark
  checks pass. Scaling comparison against the preceding local baseline detects
  no time/allocation/RSS/editor-tail regression. Added depth checking stays inside
  those gates; no runtime safety checks were disabled.
- Separate GCC 16.2.1 and Clang 23.1.1 compiler builds pass. Clang's local Conda
  installation requires `--sysroot=/`; its build also passes all 65 conformance
  fixtures. Local LLVM is 22; configured LLVM 18 CI remains separate evidence.

Exact hashes, samples, run counts and versions are retained in the accompanying
[JSON report](release-readiness-2026-09-21.json) and `build/readiness`. Timings are measurements on this host, not
portable latency guarantees. Soak duration is bounded and is not sustained user
experience or a proof of race freedom.

## Release blockers and external evidence

- Execute the prepared Windows, macOS and AArch64 probes on native runners. The CI
  YAML has been parsed and reviewed locally; no remote workflow run is claimed.
- Execute both provider CI baselines and the pinned LLVM 18 release toolchain.
- Publish the reviewed grammar, update the immutable Zed pin/provenance, then verify
  remote equality and the installed extension. Current pin differs in four of five
  checked files; the verifier correctly fails. No repository/extension was published.
- Real GPU/device execution, sustained user testing and independent security review
  remain external evidence. Those surfaces/assurances stay explicitly experimental
  or unclaimed, rather than holding up the scoped Linux development candidate.

See [release handoff](../release/handoff.md) for exact commands and artifacts.
