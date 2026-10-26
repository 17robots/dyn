# Embedded follow-up

The requested scope is embedded completion before the next language review
and self-hosting plan. These targets remain experimental.

## Current status

Implementation and focused review are complete for the requested embedded
software work: hard/soft RV32 and Thumb ABI, debug information, stack guards,
software floating point, board profile, and SSA including aggregate calls,
variadics, panic and protected cleanup. Targets remain experimental.

The durable cleanup suite passes 552 guests. Its investigation fixed a tree
capture-allocation bug; all 172 recorded SSA/tree divergences are resolved.
Combined registered repository qualification passes across the initial,
focused and resumed runs, not one uninterrupted invocation. The final segment
passes 91 gates: 69 scripts, the artifact build and all 21 artifact executions.
The earlier 39 gates are covered by prior passing runs, including corrected
pointer-width SSA expectations and canonical softfloat formatting. No runtime
skips were reported in these segments. Wasmtime is unavailable; this result
must not be described as a Wasmtime validation.

The software milestone is experimental embedded support qualified within the
documented limits. Logs are retained in build/embedded-followup under
final-suite*, final-suite-resume* and final-suite-resume2*. No commit was made
in this continuation; the working copy includes extensive earlier changes.

Remaining evidence limits:

- Physical NUCLEO-H753ZI execution is unverified; emulator checks do not replace it.
- The focused copy-forwarding reallocation regression was blocked by automatic
  review and remains unverified. Broad passes do not establish that path.
- Several internal malformed-graph/sanitizer harnesses remain temporary;
  registered tests retain production behavior and selected backend adapters.
- A possible general function-valued dereference frontend/backend mismatch
  needs a production reproducer during the later language review.

The remaining SSA opcode exclusions are not a requirement to implement every
internal form: bare-metal syscalls are rejected by semantic analysis, vectors
and jump tables are optional optimizations, and checked shifts/multiplication
have supported alternative lowering. Debug policy and resource limits remain.

## Historical implementation and verification log

The entries below record successive states. Earlier “remaining” or “in progress”
items are superseded by the current status above; they are not a fresh checklist.

## Verified in this continuation

- Thumb debug differential: 3249 cases, 3210 exact outcomes, 12 fault-class
  agreements, 26 timeout cases and one Linux-crash case inconclusive. No
  mismatches. Fault-class agreement does not establish the same fault cause.
- RV32/Thumb DWARF: 32-bit addresses, pointers and slices, target relocations,
  frame rules and Thumb frame-base bias. Live GDB tests cover parameters,
  locals, nested backtraces and stepping through return on both QEMU boards.
- Thumb aggregate copy/zero: aligned word accesses with byte prefixes/tails.
  Exhaustive oracle covers 518400 copies and 648 zero fills, all alignments,
  overlap directions, identical pointers and full-buffer canaries.
- All three bare-metal QEMU smoke suites pass in debug/release. Existing
  native debugger and assembly tests pass.
- RV32 floating aggregate C interoperability passes 139 checks per mode;
  Thumb homogeneous floating aggregates pass 242 per mode, debug and release.
- Integer and aggregate C interoperability passes 424 RV32 and 508 Thumb
  checks per mode against Clang under QEMU. This covers RV32 final-register
  splitting, Thumb core/stack splitting and large Thumb structures by value.
  Review findings for RV32 variadic aggregate alignment and unchecked writes
  at the 512-part boundary are fixed. New regressions fail before the fix
  and pass with ASan/UBSan afterward; 512-part calls compile and 513-part
  calls report an emission error. All four interop suites still pass.
  Unnamed variadic aggregate alignment is tested through the real ABI helper
  because the frontend rejects those arguments. A second review verified
  both fixes and boundary regressions with no new findings.
- NUCLEO-H753ZI flash/RAM layout, startup, power setup, initialized data,
  zeroed BSS, arena and UART pass structural and Unicorn CPU tests. External
  linking is explicitly rejected for this profile. Physical hardware remains
  unverified.
- Stack guards pass 30 QEMU checks across RV64 and hard/soft RV32 and Thumb, debug/release:
  non-tail recursion and 2 MiB frames exit 104 with `stack overflow\n`, while
  4 KiB frames succeed. RV32/Thumb live debugger tests also pass with guarded
  prologues. Independent guard review found no issues.
- The backend allocation-failure test now distinguishes optional literal-cache
  allocation from required allocations and verifies identical fallback output.
  It runs in the backend build; fresh normal and ASan/UBSan runs pass.

## Remaining

1. Review the above changes; rerun qualification after further backend edits.
2. ARM attribute-based ABI validation now passes 78 cases, the built-in
   linker regression and Thumb soft integration. Review findings are fixed:
   unsupported toolchain-specific VFP conventions, unknown mandatory tags
   and required vendor contracts are rejected. Eighteen regressions fail
   before the fixes. A second parser review found no actionable issues and
   reran all 78 cases successfully.
3. Rerun stack-overflow regression tests after further backend changes.
4. SSA support for RV32/Thumb requires width-aware descriptor loads, paired
   values, physical-register aliasing and target emission. Removing the gate
   alone would emit x86 instructions. Preserve checks and evaluation order.
   The initial implementation is present with a dedicated emitter, 8-byte value
   slots and existing paired ISA operations, bypassing native register
   allocation. Unsupported functions retain whole-function tree fallback.
   Initial Clang/QEMU differential tests pass with SSA enabled and disabled.
   Independent emitter review found no actionable issues (execution tests
   were not rerun by the reviewer). Foundation tests assert 25 named SSA and
   8 fallback selections per target, with four successful SSA/tree runs
   against Clang under QEMU. All 64 shift counts cover left, logical-right
   and arithmetic-right shifts over seven boundary values;
   most negative fixtures check lowering only. Checked integer arithmetic and
   division/remainder now pass 45 focused SSA/tree cases per target, including
   panic behavior. Independent checked-lowering review found no issues;
   durable focused tests pass 45 fixtures per target (180 guest runs), with
   named SSA selection, matching outputs/status and expected cleanup fallbacks.
   Missing-remark negative controls and prerequisite SKIPs are verified.
   Ordinary scalar integer/pointer calls are implemented, including indirect
   calls, wide results and stack arguments. Twelve call-oracle guest runs
   pass; static review found no concrete bugs. Durable call tests pass all
   12 guests, 24 named SSA functions, eight fallbacks and 32 missing-remark
   negative controls, with exact expected outputs and explicit prerequisite
   SKIPs. The separately exposed tree pointer-width cast bug is fixed:
   160 executions pass across hard/soft RV32/Thumb and host64, SSA on/off.
   The pre-fix binary fails the new raw-pointer regression; focused static
   review found no concrete issues. Scalar hard-float SSA is implemented using
   raw-bit slots and existing ISA/ABI helpers. A 61-function oracle passes on
   both targets with SSA enabled/disabled; static review found no concrete
   bugs. Durable float tests pass four guests, 122 named SSA checks and 61
   missing-remark controls, with portable overrides and temporary cleanup.
   Local aggregate/descriptor layouts, copy/zero operations and pointer/index
   guards are implemented. Temporary SSA/tree tests pass C canaries, overlap,
   boxed-any and exact panic/evaluation-order comparisons on both targets.
   A zero-byte copy optimizer bug is fixed. Durable aggregate tests pass
   38 guests and 13 missing-remark controls, covering exact panic order,
   overlap, canaries, boxed any, descriptors and zero-byte copies. Soft
   targets assert no SSA remarks and exact output. Review found zero-copy
   forwarding could widen stores without destination-alignment proof. The
   fix uses byte stores unless address facts prove alignment. Baseline RV32
   widened stores and a Thumb alignment trap are reproduced; all 38 aggregate
   guests and native SSA regressions pass afterward. Re-review found the
   known-store branch still preserved wide stores through chained copies to
   odd addresses. Both branches now require destination alignment proof;
   known-width copies retain SO_COPYMEM otherwise. Chained baseline failures
   are reproduced, and 38 guests plus 15 negative controls pass after the fix.
   Review confirms both alignment fixes. It found a stale value pointer after
   a rejected forwarding attempt reallocates the value array. The caller now
   reacquires the pointer and stops on allocation failure. The delegated
   focused reallocation regression was blocked by automatic cybersecurity
   review, so targeted reproduction remains unverified. Existing aggregate
   tests do not establish coverage of that specific reallocation path.
   Descriptor callable ABI support now preserves argument grouping, captures
   incoming parts before scratch operations, and snapshots complete result
   banks. The durable descriptor suite passes four SSA/tree guests, 19 named
   SSA functions and two fallbacks per target, four frontend negatives and
   43 lowering controls. Independent scoped review found no concrete issues.
   Production frontend rejection of any returns remains intact; backend-only
   probes using a temporary diagnostic bypass do not establish language support.
   Updated foundation tests pass 30 SSA selections and three fallbacks per
   target; scalar-call tests pass 12 guests, 29 selections and three fallbacks.
   Struct/raw-array callable ABI implementation now includes target result
   plans, hidden sret, argument snapshots, parameter reconstruction and atomic
   result-bank capture. The builder reports 164 named SSA functions passing
   independent Clang oracles in both target SSA/tree modes, plus seven focused
   regression suites and sanitizer preflight checks. Independent static review
   found no issues in the scoped implementation; it did not rerun tests.
   Durable aggregate-call tests retain all 164 named functions. All four
   RV32/Thumb SSA/tree guests produce exact ABI OK output, and 164 missing-
   remark controls pass. Prerequisite skipping and cleanup after success and
   injected failure are verified. Parent reruns of updated foundation, calls,
   descriptors and checked tests pass, including all 180 checked guest runs. Variadic/protected calls and soft SSA
   remain excluded; full coverage is unfinished.
5. Soft-float support requires a distinct ABI and software arithmetic helpers;
   current Thumb high words also occupy VFP registers.
   All 34 integer-only IEEE754 helpers are implemented. Independent C-oracle
   tests pass 7,578,342 default-seed and 14,718,342 second-seed checks in each
   of debug and release. Review found a subnormal narrowing test gap, fixed
   by generating true midpoints with fixed 2^-149 spacing and neighboring
   f64 values for both retained parities. The revised default suite passes
   7,577,390 checks per debug/release mode. RV32 soft lowering and conditional
   startup are implemented; runtime selection, cache identity and build
   artifacts are wired. Soft startup assembles with ELF flags zero after
   correcting an out-of-range immediate and a preprocessor incompatibility.
   `riscv32-none-soft` target/ABI integration and runtime builds pass. The
   existing bare-metal smoke image executes on QEMU SiFive E31 without an
   FPU. The linker accepts bare RV32 ILP32 objects and rejects mixed floating
   ABIs. Dedicated floating-expression/interop tests and full-image audits
   pass in debug/release on FPU-less QEMU SiFive E31: arithmetic, conversions,
   remainder, NaNs, subnormals, callbacks, spills, aggregates and variadics.
   Executable-section scans find no FP instructions; ELF flags and mixed-ABI
   rejection pass. Independent integration review found no concrete bugs;
   this is not a proof of full numerical correctness.
   Target integration must remove FP instructions from startup, unwinding,
   argument capture, conversions and the full linked support image, not only
   arithmetic expressions. Thumb now has frame-backed internal high words,
   comparison state and integer helper adapters, with focused preservation
   and unwind harnesses passing. Soft runtime artifacts and selection are
   wired; startup assembles with EABI5 soft-float flags. Target/ABI and DWARF
   integration pass builds and smoke execution. Live GDB tests pass for both
   soft targets, including locals, nested frames and returns. Thumb diagnostic
   runs pass debug/release arithmetic, C ABI, recursion, disabled CPACR,
   mixed-ABI rejection and four panic cleanups. ARM mapping symbols now mark
   code, vectors, literals and padding. The strict full-image VFP audit passes
   with debug/release and checked-panic execution; no audit bypass remains.
   Independent correctness and mapping metadata reviews found no actionable
   issues. Unflagged Clang ABI validation now passes dedicated tests;
   independent attribute-parser review is complete with no actionable findings.
6. First physical profile: NUCLEO-H753ZI implementation and flashing/debugger
   instructions are present. Hardware execution remains unverified until an
   actual board is available.
7. Full qualification and authorized commit. Preserve prior unrelated work;
   compiler working copy already contained extensive changes at handoff.

Then refresh the language review and plan self-hosting.

## Active follow-up

Soft-float SSA integration now uses soft remainder helpers and Thumb core/sret
aggregate result plans. The builder reports both-target SSA/tree Clang ABI
oracles, named arithmetic/conversion/remainder checks, full-image no-FP audits,
sanitized preflight and hard-target regressions passing. Independent static
review found no issues. The durable soft suite passes 14 guests: four aggregate,
eight arithmetic and two Thumb unwind runs. Each target checks 164 aggregate
and nine arithmetic SSA names; 173 missing-remark and two tree-remark controls
pass. Full-image no-FP audits, FPU-disabled execution and eight unwind cleanups
pass. Arithmetic uses known IEEE bit patterns through opaque calls; Clang
independently checks ABI behavior, not software arithmetic. The local aggregate suite now
requires named soft SSA selection and explicitly runs the soft tree control.
The remaining case/trap, variadic and protected-cleanup exclusions are SSA
coverage gaps; their tree-emitter language functionality already exists.

Case dispatch now uses ordered comparison chains on ILP32. Validated terminal
trap exits avoid successor access, and enum-tag guards preserve tree diagnostics.
The builder reports 56 SSA/tree guests across all four targets, including
backend-only overlap/non-exhaustive IR fixtures; production frontend rules are
unchanged. Independent static review found no issues. Durable case tests pass
24 production and 32 backend-only adapter guests, 16 frontend rejection checks,
and 19 named-remark negative controls. Soft no-FP audits and disabled-FPU
execution are retained. Separate sanitizer preflight fixtures remain temporary.
The updated foundation
suite passes 32 named SSA functions and one fallback per hard target.
Explicit panic, variadic calls and protected cleanup remain outside this slice.

Direct packed Dyn variadic SSA integration is in progress. It reuses the
synthetic slice ABI and caller-owned packing, with checked group/frame bounds
and target-width any pointer fields. Foreign variadic ABI remains a separate
slice. Native packed variadic function pointers are rejected by the frontend;
this work does not extend that language feature.

Direct packed variadic implementation now passes eight SSA/tree guests across
all four targets, with 83 named SSA functions, 40 production rejection checks,
soft no-FP audits and sanitized preflight. All ten existing SSA suites pass.
Independent review and durable packed-test retention are pending. Foreign
variadics and protected cleanup still use tree fallback.

The durable packed suite passes eight guests, 40 production rejections,
83 missing-remark and 83 fallback-remark controls, plus soft image audits.
Review found that capacity/pack-size checks constructed argument SSA before
rejecting oversized calls. The fix moves complete grouped ABI and uint64 pack
checks before argument construction. The pre-fix baseline fails the new
zero-emission assertion; normal/sanitized preflight and focused regressions
pass after the fix. Fresh review found no issues and reran normal and
sanitized preflight on all four configurations successfully. The internal
harness remains temporary rather than a registered regression.

Foreign C variadic SSA call-site implementation is in progress. It requires
call-specific named/unnamed classification on RV32 and base PCS for all Thumb
arguments and results. Inferred pointers to foreign variadic functions are in
scope; new frontend syntax, unnamed aggregates and C variadic definitions are
not. Cleanup remains a separate slice.

Foreign variadic call-site implementation passes the independent Clang va_list
oracle: 140 named SSA functions and eight SSA/tree executions across four
targets. Soft no-FP audits, actual indirect instructions, sanitized preflight
and 64 frontend rejection checks pass. Independent review and durable test
retention are pending. The old deadvariadic fallback expectation is updated.

Foreign variadic review found no issues (static review). Durable tests pass
eight guests, 64 frontend negatives, 140 missing-remark and 140 fallback-remark
controls, eight actual indirect-instruction assertions, and four soft-image
audits. FPU-disabled execution, cleanup and missing-tool SKIP checks pass.
The parent-updated call suite passes 12 guests with 31 SSA functions and one
protected-call fallback. Panic and protected cleanup SSA are being mapped next.

Standalone unprotected panic SSA is the next implementation slice. Protected
cleanup additionally needs cross-block result capture, explicit landing edges
with stack restoration, and cleanup-aware checked multiplication. Runtime
unwind layouts can remain unchanged. Cleanup support will not imply universal
SSA: syscall/runtime forms, vector lowering and policy/resource limits require
separate assessment.

Standalone panic implementation is reviewed with no issues; normal and
sanitized preflight were rerun successfully. Durable tests pass 64 production
and 48 backend-only ABI/trap guests, with 19 remark controls and soft no-FP
checks. The foundation suite now requires all 33 fixture functions to use SSA.
Protected cleanup implementation is in progress, including cross-block result
capture, landing stack restoration and cleanup-aware multiply overflow.

Protected cleanup SSA implementation is present but not yet qualified. The
builder reports 208 SSA trace runs matching expectations, ABI oracles and
sanitized preflight passing. However, 172 SSA/tree comparisons diverge,
including four tree timeouts. Only two representative failures are proven
byte-identical with pre-patch tree output. Independent SSA review and tree
root-cause investigation are active; no blanket preexisting-bug conclusion
or full equivalence claim is made.

Tree diagnosis identifies a shared descriptor capture allocation mismatch:
count_scratch reserves eight bytes for ILP32 string/slice captures, while the
model-register capture representation stores sixteen bytes. Adjacent captures,
guard message staging and call-result staging can overwrite pointers/lengths.
Representative Thumb timeouts are unbounded corrupted output, not demonstrated
unwind deadlocks. A driver-only allocation fix is in progress; all cleanup
comparisons must be rerun before declaring the divergences resolved.

The driver-only descriptor capture allocation fix resolves all 172 recorded
mismatches: all 416 cleanup executions now match exact expected results.
Minimized pre-fix failures are reproduced; guards, snapshots, ABI and host64
controls pass. Fresh capture-fix review and durable cleanup test retention are
active. Older protected-function fallback expectations now require SSA.

Durable cleanup qualification passes 552 guests: 416 original traces, 120
capture/guard/snapshot cases and 16 protected ABI cases. Named SSA checks,
soft-image audits and strict guest output/time bounds are retained. The capture
allocation fix review found no issues. Updated calls, descriptors, checked,
cases and panic suites pass. Full repository qualification and a final audit
of remaining fallback boundaries are now active.

Broad qualification has passed all 20 gates from stack tests through
documentation snippets, including every registered embedded SSA suite,
debugger and board-profile checks, with no skips in that segment. Formatter
then found noncanonical whitespace in softfloat.dyn. Repository formatting
was applied; whitespace-stripped contents are identical, and the formatter
suite passes all 116 std/runtime/vendor modules. Qualification resumes at the
scale benchmark; subsequent broad gates and C artifact tests remain pending.
