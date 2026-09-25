# Browser WebAssembly (experimental)

Dyn can build a freestanding `wasm32-browser` module callable from JavaScript.
The separate `wasm32-wasi` target builds WASI Preview 1 commands. Neither target
is an Emscripten-compatible runtime or a complete port of the native SDK. Requires LLVM with the WebAssembly backend, Clang and
`wasm-ld` on the compiler host. Node is required for the executable test gate.

```sh
just release
build/dyn build projects/browser-canvas --target wasm32-browser --shared \
  --release --output projects/browser-canvas/canvas.wasm
python3 -m http.server 8000 --directory projects/browser-canvas
```

Open http://localhost:8000. JavaScript fills a buffer in the module's memory;
Dyn applies grayscale and calls JavaScript to report completion. See
[the example](../projects/browser-canvas/main.dyn).

## Module interface

Root-module `pub fn` declarations are exported with their Dyn names. Imported
packages' public functions are not automatically exported. `extern fn` uses
its explicit link name under JavaScript's `env` import object. Only declared
foreign functions may become unresolved imports; missing runtime symbols fail
linking. Additional Wasm C objects can be supplied using `--link`.

```js
const { instance } = await WebAssembly.instantiate(bytes, {
  env: { pixels_changed(count) { console.log(count); } },
});
const dyn = instance.exports;
dyn.dyn_initialize(); // Required before calling application functions; idempotent.
const pointer = dyn.allocate(4096) >>> 0;
if (!pointer) throw new Error('Arena exhausted');
const pixels = new Uint8Array(dyn.memory.buffer, pointer, 4096);
```

The compiler reserves `dyn_initialize`. Initialization may call imports, so those
imports must be ready; do not reenter application exports during initialization.
Export scalar numbers and pointer/count pairs for a simple JavaScript interface.
Pointers, `usize`, and `isize` are 32-bit; slices contain a 32-bit pointer and
32-bit length. `i64`/`u64` cross JavaScript as BigInt. Interpret pointer results
with `>>> 0`. C structs use Wasm Basic C ABI lowering; Dyn slices and payload
enums are not a JavaScript object representation. C variadic functions are
currently rejected. Exported global variables and a callback-table interface
are not part of this first interface.

## Memory and failure

Use `std/mem.arena_from_buffer` over module-global or caller-provided storage.
Function-local buffers must not escape their call. Reset/rewind invalidates every
affected allocation, including JavaScript views. `arena_create` now obtains backing
through Wasm `memory.grow`. Released page ranges are reused, split and coalesced
inside `std/mem`; linear memory cannot shrink. Existing allocations never move.
Growing arenas acquire additional blocks through this same interface. Fixed
buffer-backed arenas never fall back to growth on exhaustion. Allocation failure
returns the existing error result without changing live allocations. This allocator
is thread-confined; no shared-memory or reentrant allocation contract is promised.
No ownership packages or standalone malloc interface are added.

The module exports its linear memory. Host code must respect allocation bounds
and lifetime; linear-memory bounds do not validate individual Dyn allocations.
Any call which grows memory (including `arena_create` and growing arena pushes)
can detach existing JavaScript views. Recreate views from `exports.memory.buffer`
after such calls. Numeric Dyn pointers remain stable. Use `--link --max-memory=N`
(bytes, multiple of 65536) to set a linker-enforced memory ceiling.

Fatal Dyn checks and `#panic` trap. Normal returns run `defer`; explicit local
panic cleanup follows existing code generation, but Wasm traps and JavaScript
exceptions do not unwind caller defers. Discard an instance after a trap or an
exception crossing an import; its stack or application state may be incomplete.
The initial stack reservation is 1 MiB. Panic text/native stack traces are not
exposed by this minimal runtime.

Native syscalls are rejected. Files, sockets, processes, threads, native shared
libraries and browser DOM access are not supplied by the browser target. Implement
needed browser services through explicit JavaScript imports. Only the exercised
SDK subset is qualified; adding a target does not make every std package portable.

## Evidence

`python3 tests/wasm-browser.py` executes debug/release modules through Node's
WebAssembly interface, including imports, exports, target layouts, Clang struct
ABI calls, arena failure/reset, initialization, and pixel processing. This is
engine execution, not a claim of testing every browser UI or mobile browser.

ABI references: [Wasm Basic C ABI](https://github.com/WebAssembly/tool-conventions/blob/main/BasicCABI.md),
[LLD WebAssembly](https://lld.llvm.org/WebAssembly.html).

## WASI Preview 1 commands

```sh
just --justfile projects/justfile wasi
node tools/run-wasi.mjs projects/build/wasi-hello.wasm hello world
```

Build with `--target wasm32-wasi` without `--shared`. The command exports `_start`
and `memory` and imports WASI services from `wasi_snapshot_preview1`; `main` performs
normal global initialization exactly once. Commands currently use whole-program
code generation, not the native incremental object cache. `dyn run` is rejected:
run the `.wasm` using an explicit host. Shared/reactor modules and Preview 2
components are not implemented.

`std/os/wasi` supplies argument copies into a caller arena, descriptor read/write,
close, relative read-only opens, random bytes and clock time. `std/terminal`
provides stdin/stdout/stderr adapters for `std/io`. File operations use directory
descriptors granted by the host; the included runner grants none. Broader `std/fs`,
processes, sockets and threads are not ported. Low-level WASI errors remain errno
values; stream adapters use the existing negative-error convention.

The Node host is used for execution tests, not as a claim of security isolation;
see [Node's WASI contract](https://nodejs.org/api/wasi.html).

## FFmpeg in the browser

[Browser video example](../projects/browser-video/README.md) combines the pinned
single-thread FFmpeg Wasm core with a separate Dyn module in a worker. JavaScript
copies decoded frames between the two memories; Dyn storage uses an arena. This
is independent of native `vendor/ffmpeg/raw` bindings. A job can be cancelled by
terminating its worker. The example caps input size, frame count and processing
time; it is a short-clip demonstration rather than an editor or a streaming engine.

## Additional validation

`tests/wasm-memory.py` executes growth, stable pointers, split/coalesce, reuse,
fixed-buffer exhaustion, growing arenas and deterministic memory-limit failure.
`tests/wasi.py` covers command arguments, stdio, preopened files, missing grants,
EOF/error behavior, clocks and random calls. Installed-SDK tests repeat these.
`tests/browser-ffmpeg.py` runs real decode/filter/encode in both compiler modes;
the Node harness supplies the browser-worker location expected by the pinned core.
`tests/browser-video-ui.cjs` additionally runs the real worker/UI in Chromium,
including malformed input, cancellation, retry and playable output metadata.

For editor analysis use `dyn lsp --target wasm32-browser` or
`dyn lsp --target wasm32-wasi`. The target is fixed for that server process and
applies to diagnostics, imports and completion; use separate server instances
for projects with different targets.
