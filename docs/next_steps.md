# Next Steps

Checked on 2026-04-14.

## Now

- `compiler-dyn` analyzes cleanly under Rust bootstrap
- `compiler-dyn/main.dyn` has a minimal single-file `lex|parse|analyze` path
- `std/io` now loops for `read_exact` and `write_all`

## Next

1. replace placeholder generic printing in `std/io/writer`
2. add behavior tests for compiler-facing std runtime paths
3. add multi-file/module loading to `compiler-dyn`
4. extend `compiler-dyn` sema beyond declaration/name analysis
5. define Rust-backend handoff shape for self-host frontend output

## Self-Hosting Order

1. keep Rust compiler bootstrap source of truth
2. finish compiler-facing std
3. bring up Dyn compiler in stages:
   - lex one file
   - parse one file
   - sema one file
   - process own source subset

## Risks

- associated method typing now works, but generic nominal-type resolution still weak spot
- std mostly compile-tested; runtime behavior coverage still thin
- self-host frontend is alive, but still only single-file
- std behavior still less tested than std surface
