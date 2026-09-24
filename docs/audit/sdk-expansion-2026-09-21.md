# SDK expansion and correctness followup

Authorized scope: DNS answer ownership; compiler stress coverage; ZIP central
validation/data descriptors; TAR PAX/GNU long names; XML namespaces/Unicode names;
portable process interface with bounded concurrent output capture; filesystem
watching; Unicode operations; property testing/shrinking/temp-directory cleanup;
existing vendor binding depth, ABI and allocation-policy review.

## Implemented

- DNS resolves bounded CNAME chains independently of answer order before collecting
  matching A/AAAA addresses. Canonical label sequences preserve label boundaries;
  unrelated owners cannot inject addresses. Cycles, malformed and conflicting
  aliases fail. No heap allocation. Regression failed against old parser.
- Compiler stress runs two million nested callback/aggregate/defer iterations under
  a 1 MiB stack limit in debug and release, checked against an independent checksum.
- ZIP adds checked central-directory iteration and signed/unsigned data descriptors.
  Extract checks exact DEFLATE consumption. Fixed streaming extra fields overwriting
  the header before its CRC was read.
- TAR buffered reader retains global PAX state; local PAX/GNU metadata is consumed
  internally. Streaming metadata uses an explicit arena. Repository callers migrated.
- XML supports Unicode names and caller-storage namespace scope/resolution with
  normalized URIs, reserved binding checks, rollback, and expanded-attribute uniqueness.
  Writers reject invalid names/characters before emitting them.
- Unicode 17 tables and generator provide properties, full default folding, NFC/NFD/
  NFKC/NFKD and extended graphemes. Official data hash and license are retained.
- Property testing generates seeded byte inputs and shrinks failing examples within
  a check budget. Fixed existing xorshift truncation traps in debug builds; deterministic
  sequence test added. Temporary directories have explicit, symlink-safe cleanup using
  caller frame/scratch buffers.
- Linux filesystem watching exposes nonrecursive inotify events, rename cookies,
  empty/error distinction, and sticky overflow/rescan state.
- Process interface provides explicit environments, spawn/wait/terminate/pipes and
  simultaneous bounded stdout/stderr capture. Linux, macOS and Windows adapters share
  capture/validation logic. Linux/macOS report exec failures immediately and safely
  duplicate redirect sources. Windows uses UTF-16, CRT quoting and a restricted handle list.
- Fixed missing Linux AArch64 mappings for fork-style clone and fsync; fixed dup2/dup3
  same-descriptor behavior. Darwin libSystem linking resolves through target SDK.
- SQLite gains transaction state/control, busy timeout and 64-bit changes/row IDs.
  All provider allocation/lifetime policies documented; no hidden allocator-hook install.
- Expanded SDK exposed LSP's filesystem-order-dependent import quickfix. It now returns
  up to 32 unique, sorted alternatives; ambiguous results aren't preferred. Path validation
  is shared with completion, and import edits convert byte positions to wire columns.

## Validation

Passed locally (logs in `build/sdk-expansion/`):

- `make test-c`: compiler/contracts/runtime/LSP suites, including the new stress case.
- `make sanitize-test-c`: ASan/UBSan, failure injection, runtime and editor audit cases.
- `make per-file` and `make test-static-analysis`: separate translation units build;
  26 compiler translation units report no analyzer warnings.
- `make test-libraries`, then final `tests/library-contracts.py` after interface fixes:
  all SDK fixtures in debug/release and native provider contracts.
- 403,031 official Unicode vectors in debug/release; repeated using the sanitized
  compiler. Generated tables reproduced byte-for-byte from the pinned archive.
- New DNS, ZIP, TAR metadata, process, namespace, watch, property and temporary-directory
  contracts; final process tests include closed-descriptor reuse and arena exhaustion.
- `projects/validate.sh`: all projects pass; GPU unavailable is explicitly reported.
- Windows process ABI assertions compiled against Zig's Windows SDK. PE32+, Mach-O arm64,
  and AArch64 Linux process/watch outputs cross-link successfully.

Added native process probes and a checksum-pinned Zig 0.16.0 install to CI. These CI
changes have not been executed remotely. Source/inventory migration checks passed;
118 SDK source files inventoried.

Native Windows/macOS execution is unavailable locally. Added native CI process probes;
PE/Mach-O cross-linking and Windows SDK ABI assertions are checked locally. Linux
AArch64 process/watch cross-builds are checked, not executed. Filesystem watching and
recursive cleanup currently target Linux. GPU runtime/provider-version matrices remain
outside locally executed coverage. No grammar publication or deployment performed.

See [interfaces and limits](../sdk-additions.md),
[migrations](../library-migrations.md), and [provider allocation policy](../vendor-allocation-policy.md).

Followup: [SDK/compiler hardening](sdk-hardening-2026-09-21.md) supersedes the
TAR streaming metadata arena interface with bounded reusable caller byte storage.
