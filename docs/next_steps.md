# Next Steps

Checked on 2026-04-11.

## Now

- `std/mem/allocator` typed helpers: done
- `std/mem/arena`: in progress
- compiler sema method-call path: fixed for associated methods + implicit receiver calls

## Next

1. finish `std/io/reader` real `read_all`
2. audit `std/io/writer` and `std/os/file` for compiler-grade read/write paths
3. add allocator tests:
   - zero-sized types
   - arena save/restore/reset
   - allocators without native realloc
4. audit nominal type vs type-param resolution in sema
5. choose first Dyn self-hosting slice:
   - token/span types
   - lexer
   - diagnostics formatting

## Self-Hosting Order

1. keep Rust compiler bootstrap source of truth
2. finish compiler-facing std
3. port `compiler-dyn/old` toward current language + std surface
4. bring up Dyn compiler in stages:
   - lex one file
   - parse one file
   - sema one file
   - process own source subset

## Risks

- associated method typing now works, but generic nominal-type resolution still weak spot
- std mostly compile-tested; runtime behavior coverage still thin
- `compiler-dyn/old` still best logic donor, but compatibility port not started yet
