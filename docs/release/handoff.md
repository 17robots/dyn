# Candidate validation and release handoff

Run from the workspace root, with the toolchain in `docs/toolchain.md`:

```sh
RELEASE_FLAGS=--baseline just release-check
# Additional target and provider qualification, retained separately:
python3 tests/provider-matrix.py
python3 tests/readiness-native.py --cross
python3 tests/aggregate-abi.py --cross
```

See [validation](validation.md) for dependency setup, partial development runs,
per-stage logs and exact candidate archives. Omit `--baseline` only for a local
candidate with its actual toolchain recorded. Native execution and publication
remain separate from the aggregate Linux gate.

Run commands sequentially when they share fixture outputs. Keep the exact compiler
hash, toolchain/provider versions, logs and `build/readiness`/`build/dist` artifacts.
A reproducibility pass compares builds with the same absolute source/SDK paths and
toolchain; it does not promise path-independent debug objects or cross-toolchain bytes.

The CI workflow contains native Windows x86-64, macOS AArch64 and Linux AArch64
execution jobs. A successful Linux cross-link does not close those rows. Provider
jobs build on Ubuntu 22.04 and 24.04 instead of transferring binaries built against
newer glibc onto older systems. The older baseline obtains LLVM 22 through the
[official LLVM repository](https://apt.llvm.org/), verifying its signing-key
fingerprint; the primary release baseline stays LLVM 19.

For Zed distribution, `build/dist/dyn-grammar-candidate.tar.gz` contains the reviewed
source/generated grammar, corpus and editor queries. `grammar-publication.json`
records every file hash. Apply and review these files in the upstream grammar
repository, publish its commit, then update `zed-dyn/extension.toml` and
`zed-dyn/grammars/provenance.json` to that immutable commit. Run
`just verify-published-grammar`, then test the installed extension. Do not replace
the pin with a made-up or unpublished revision. Preparing this bundle does not
publish a repository or extension.

Before removing `-dev`, record successful native jobs, exact provider baselines,
installed editor behavior and the release decision in `readiness.md`. Hardware-
dependent surfaces remain experimental unless actually exercised. Independent
security review and sustained real-user operation require separate evidence.
Freeze syntax and API scope during this process; self-hosting is a later project.

## Developer preview versus stable release

A Linux x86-64 developer preview may keep `0.1.0-dev`, ship the tested Linux
compiler/SDK, and label other targets and provider/hardware surfaces experimental.
Its manifest must record actual system dependencies and toolchain versions; a
local LLVM 22 artifact is not the pinned LLVM 19 release build. Shipping a preview
does not close native cross-target, editor publication or independent-review rows.

A stable release requires the evidence promised by its declared support matrix.
Do not delay an experimental preview for new syntax, generics or self-hosting.
Do not remove experimental labels just because cross-linking or semantic checks
pass. Keep known limitations and migration notes with the downloadable artifact.
