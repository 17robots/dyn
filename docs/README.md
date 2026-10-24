# Dyn documentation

Start with [idiomatic Dyn](guide/idiomatic-dyn.md), then keep the
[language reference](guide/language.md) and [standard library](guide/std.md)
pages at hand. `dyn docs std/<module>` prints any module's declarations and
contracts straight from the source.

## Writing Dyn

- [Idiomatic Dyn](guide/idiomatic-dyn.md): how to write clear, correct Dyn
- [Language reference](guide/language.md): the exact rules
- [Style](guide/style.md): layout and naming
- [Memory and ownership](guide/memory.md): arenas, lifetimes and failure policy
- [Memory patterns](guide/memory-patterns.md): tested example programs
- [Buffer contracts](guide/buffer-contracts.md): caller-buffer functions and their errors
- [Collections](guide/collections.md): builder, string map and slot map
- [Standard library](guide/std.md): conventions and every package
- [Operation costs](guide/costs.md)
- [Writing Dyn with an agent](guide/agent-guide.md)

## Platforms and interop

- [C interop (FFI)](guide/ffi.md)
- [Vendor packages](guide/vendor.md): optional native library bindings
- [SQLite](guide/sqlite.md) and [TLS](guide/tls.md)
- [WebAssembly](guide/webassembly.md)

## Tools and process

- [Tools](guide/tools.md): the `dyn` command, queries, sandbox and benchmarks
- [Debugging](guide/debugging.md)
- [Security](guide/security.md)
- [Stability](guide/stability.md): what may change between releases
- [Changelog](../CHANGELOG.md) and [migration guides](migrations/)

## Compiler internals

- [Compiler architecture](internals/compiler.md)
- [Shared frontend](internals/frontend.md): analysis used by the compiler and the language server
- [Settled decisions](internals/decisions.md)
- [Generics design](internals/generics-design.md)
- [Standard-library ABI](internals/standard-library-abi.md)
- [Reflection ABI](internals/reflection.md)
- [Releasing](internals/release.md)
- [Self-host plan](internals/selfhost-bootstrap.md)
- [Readiness review](internals/readiness-20261024.md)
- [Structural IR snapshot](internals/ir-dump.md)
- [Std contract migration](migrations/std-contracts-20261024.md)
