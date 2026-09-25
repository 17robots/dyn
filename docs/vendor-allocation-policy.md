# Native provider allocation policy

Dyn-owned heap storage goes through `std/mem`. Passing an arena for conversion or
output does **not** redirect a native library's internal allocations. No wrapper
silently installs process-global allocator hooks. These policies describe the
shipped bindings, not a guarantee that an entire native dependency is heap-free.

| Provider/path | Allocation and lifetime |
| --- | --- |
| SQLite | Provider-owned database, prepared statements and copied bound values. Finalize statements, then close database. Failed/busy close retains the handle. |
| OpenSSL crypto | Provider-owned temporary EVP contexts/keys, released within each operation. Discard unauthenticated/failed output. |
| OpenSSL TLS | Provider-owned contexts, connections and referenced certificates, with explicit matching releases. Socket ownership stays with caller. Arena parameters hold conversion buffers only. |
| SDL3 | Provider-owned windows, renderers, audio streams and GPU handles; use matching destroy/release functions and retain callback context until native callbacks stop. GPU/device allocations are not ordinary arena storage. |
| Vulkan loader | Procedure lookup returns borrowed native function pointers. Instance/device lifetimes and generated commands remain application-owned. No implicit allocator callback installation. |
| zstd one-shot | Provider may allocate internal contexts. Caller buffers/arena helpers own only input/output/conversion storage. |
| zstd streaming decoder | Uses `ZSTD_initStaticDStream` in caller workspace, with explicit window limits. Workspace outlives context; never pass it to native context-free functions. Advanced ABI is version-sensitive. |

SQLite supports process-global memory configuration with initialization/threading
constraints. OpenSSL also offers global memory hooks; SDL offers memory-function
replacement. A short-lived per-operation arena cannot satisfy those global
lifetimes, reallocations, synchronization, or native subsystem requirements.
Adding hooks would require a separate, explicit application initialization contract.
The current bindings do not claim arena-only provider internals.

Authoritative contracts:
[SQLite configuration](https://www.sqlite.org/c3ref/config.html),
[OpenSSL memory functions](https://docs.openssl.org/3.0/man3/OPENSSL_malloc/),
[SDL memory functions](https://wiki.libsdl.org/SDL3/SDL_SetMemoryFunctions),
[zstd static API](https://github.com/facebook/zstd/blob/v1.5.7/lib/zstd.h).

Validation includes SQLite handle/error/state tests (including 64-bit row IDs and
transactions), OpenSSL known-answer/failure cases, zstd independent producer
round-trips and bounded streaming, and SDL/Vulkan header layout/callback probes
where development headers are installed. These are specific contracts, not proof
of compatibility with every provider release or driver.
