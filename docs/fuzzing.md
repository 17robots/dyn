# Fuzzing and regression handling

`just fuzz-c` runs the deterministic compiler maturity gate. It covers malformed parser/checker
inputs, valid programs through LLVM and the runtime, debug/release differential behavior, and a
generated corpus of C headers through `dyn-bind` and back through the Dyn checker. It needs no
network service and is suitable for CI.

The default run uses seed 1 and 96 parser cases. Reproduce or broaden it with:

```sh
DYN_FUZZ_SEED=731 DYN_FUZZ_CASES=1000 just fuzz-c
DYN=./build/dyn-sanitize DYN_FUZZ_SEED=731 tests/fuzz-smoke.sh
```

Seeds and case counts must be non-negative decimal integers. Generation is intentionally stable:
the same compiler checkout, seed, and count produce the same source sequence. A crash or
debug/release mismatch is copied below `build/fuzz-smoke/` with its replay seed in the diagnostic.

## Turning failures into regressions

1. Preserve the generated artifact and exact command, compiler revision, target, seed, and sanitizer
   output before reducing it.
2. Minimize tokens or declarations while replaying the same compiler phase and failure. Do not
   normalize away invalid syntax: parser recovery is often the behavior under test.
3. Store the smallest stable input under a purpose-named `tests/` directory and add an assertion to
   `tests/run.sh`. Assert the public diagnostic or behavior, never an address or stack trace.
4. Keep the original seed in a comment so the surrounding generated corpus remains reproducible.
5. Run `just test-c`, `just sanitize-test-c`, and `just fuzz-c`. A minimized case supplements the
   seeded generator; it does not replace it.

This is a bounded deterministic gate, not a claim of exhaustive fuzzing. Long-running CI can sweep
distinct seeds and upload only failing artifacts. Inputs remain local and contain no secrets.
The scheduled C-compiler workflow runs four sanitized 5,000-case shards nightly and retains any
crashing input as a build artifact. A green workflow is evidence for that run, not proof of absence.

`tests/typed-metamorphic.py` adds 24 seeded, valid typed programs, each built as a
root and imported module, with/without comments, in debug/release (192 builds).
It checks parameter/local collisions with module functions, indirect calls,
reflection and address-taking. `tests/sema-table-growth` forces reflection to
grow expression/item tables during nested checking. These regressions supplement
malformed-input fuzzing; they do not assert every generated program is valid.
