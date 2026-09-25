# Dyn bootstrap compiler

Build from this directory; the root workspace justfile only delegates here:

Build commands require `just`, Python 3, and Bash. Set configuration through
environment variables before the command.

```sh
TS_DIR=../tree-sitter-dyn just release
just smoke
./build/dyn --version # standalone checkout; workspace builds use ../build/dyn
PREFIX=/usr/local DESTDIR=/path/to/staging just install
just package
```

The Linux host build requires a C11 compiler, LLVM headers/shared library,
Tree-sitter runtime headers/library, and Clang for cross-target runtime objects.
`LLVM_CONFIG=llvm-config-19` (or another supported installation) selects LLVM.
`TS_DIR` points to a separate Dyn grammar source checkout, including generated
`src/parser.c`, `src/scanner.c` and headers. Regeneration delegates to that
checkout's justfile and requires its pinned Tree-sitter CLI. No parent justfile
is required for build, smoke, install or packaging.

In the combined workspace, output defaults to `../build` for compatibility.
Outside it, output defaults to `./build`. Override with `BUILD=/absolute/path`.
`CC`, `CLANG`, `CFLAGS`, `CPPFLAGS`, `LLVM_CONFIG`, `PREFIX` and `DESTDIR` are
configurable. A compiler at a custom output path may need `DYN_SDK` pointing to
this directory when run directly; installed SDKs find their own libraries.

`just package` produces `BUILD/dist/dyn-0.1.0-dev-linux-x86_64.tar.gz`, checksum
and manifest, then verifies an unpacked/relocated install. System LLVM,
Tree-sitter and native providers are not bundled. `tools/dyn-bind.py` and the
packager travel with this compiler checkout. Packaging prepares files; it does
not publish a release or change version numbers.

`just test` runs the shared suite when the workspace fixtures exist, or the local
smoke test in a standalone checkout. Full compiler/LSP/SDK qualification targets
(`test-c`, `quality-c`, `test-libraries`, `test-readiness`, etc.) live in
`workspace.just` and require `WORKSPACE=/path/to/combined/workspace`, including
its tests, tools, benchmarks and editor checkouts. They do not claim standalone
smoke coverage is equivalent to full release qualification.

Current compiler lowers `fn main()`, void `return`, typed and inferred primitive locals,
primitive expressions, assignments, and checked arithmetic. Bare expressions are not valid statements.
Scoped `if`/`else`, condition and infinite `for` loops, `break`, `continue`, and branch-local
`return` lower to LLVM control-flow blocks. `for item in collection` traverses arrays and slices;
`continue` advances before retesting.
Nominal structs lower to LLVM named structs; packed declarations lower to packed LLVM bodies.
Construction starts from zero, applies declaration-order defaults, then explicit literal fields.
Function signatures are collected before body checking, enabling forward calls and recursion.
LLVM emission declares every function before generating bodies and preserves typed parameters,
results, and aggregate value semantics.

`ir.h` exposes typed IR through two operations: `dyn_ir_lower` and `dyn_ir_free`. Lowering
removes source spans/names except emitted symbols, normalizes compound assignments, and validates
all value, statement, local, function, aggregate, and child-list references. LLVM lowering never
reads semantic AST data.

Pointer types are interned as `(pointee, const)` pairs and copied into typed IR. LLVM uses opaque
thin pointers. Every generated dereference and pointer-based field access checks nil and target
alignment in debug and release; failure enters `dyn_panic` and exits 101.
Fixed array types and slice descriptors are interned beside pointers and preserved in typed IR.
LLVM uses native arrays and `{ptr, i64}` slice values. Array literals zero-fill omitted elements;
index and range guards remain enabled in release builds. Arrays copy by value and slices copy their
descriptor. Pointer-binding `for *item` / `for *const item` is supported, subject to source mutability.
Enums use calculated tag/payload layouts and LLVM tagged aggregates. `case` normalizes integer
ranges, rejects overlap, proves integer/enum exhaustiveness, and copies payload bindings.
Later constructs receive explicit not-implemented diagnostics. Output is static Linux x86-64
ELF from LLVM object generation and `ld.lld` (or development fallback `ld`).

See `docs/compiler.md`, `docs/debugging.md`, `docs/language.md`, `docs/decisions.md`, and
`docs/release/readiness.md`.

With the full workspace, `just release-check` runs the Linux preview release
gates and saves logs, dependency versions and archive hashes. See
`../docs/release/validation.md` for local versus pinned-baseline qualification.
Standalone compiler checkouts use `just smoke` and `just package`; full release
qualification additionally needs the workspace integration fixtures.

Optional providers: `just vendor-libs` builds the pinned native game/asset/audio
libraries and small ABI adapters. `VENDOR_PACKAGES='cgltf box2d'` selects packages.
Installed SDKs include `dyn-build-vendors` and the adapter sources; native provider
binaries remain separate dependencies. See `../docs/vendor-game-libs.md`.

Full raw vendor declarations are generated from matching native headers with
`just vendor-bindings` (installed SDK: `dyn-bind-vendors`). The output defaults
to `build/raw-sdk`; set `DYN_SDK` to that overlay. Existing convenient vendor
modules remain available. See `docs/vendor-raw-bindings.md` in the workspace/SDK
for dependencies, allocator contracts, coverage reports and dispatch APIs.

After generation, `. ./build/raw-sdk/env.sh` activates the matching compiler,
imports and native library paths. `dyn-bind-vendors --list` lists available
groups. Building Lua also provides an executable borrowed-string/arena example
at `build/raw-sdk/examples/lua`.

Browser-callable modules: see [WebAssembly setup and contracts](../docs/webassembly.md).


Declaration lookup for tools and agents:

```sh
./build/dyn docs std/strings --json
```

Use `../build/dyn` in the combined workspace. JSON contains public declarations,
source contracts/locations, target gates and a source fingerprint. This is syntax
inspection, not type checking or a complete program database; validate applications
with `dyn check`. See the workspace's `docs/agent-guide.md` for memory patterns and
`just test-agent-readiness` for focused query/memory qualification.

## License

Copyright (c) 2026 Matthew Dray <mdray@duck.com>. See [LICENSE](LICENSE).
Commercial applications are allowed. Dyn modifications are limited to contributions;
independent Dyn distributions are prohibited, subject to the stated exceptions.
This is source-available software, not open source.
