# Write-anything work program

Each batch must end in executable tests, ownership documentation, and honest target support.

- [x] Windows x86-64 and macOS AArch64 file/memory/network/event adapters; Windows threads.
- [x] Windows/macOS adapter probes are built on Linux and executed by native GitHub CI runners.
- [ ] macOS native threads remain; the freestanding runtime intentionally cannot pretend pthread compatibility.
- [x] No package manager or registry. Projects use explicit local dependency roots or vendored source.
- [x] SDL3 window, renderer, input, and queued-audio bindings with explicit ownership and headless examples.
- [x] Portable SDL3 GPU device/swapchain/submit lifecycle and queued-audio stream control; deeper rendering/audio grows from applications.
- [x] Procedural Linux event registration plus x86-64 epoll and AArch64 ppoll coverage.
- [x] Windows WSAPoll and macOS poll adapters, cross-linked from Linux.
- [x] Allocation-free WebSocket frame codec and RFC 6455 SHA-1/Base64 upgrade handshake.
- [x] Allocation-free stateful WebSocket message assembly, close lifecycle, and explicit ping/pong events.
- [x] Reusable SQLite ownership wrapper and integration example.
- [x] Linux x86-64/AArch64 shared-library output and C consumer test.
- [x] Windows DLL and macOS dylib output with cross-target consumers; native execution remains CI work.
- [x] Bounded LSP document synchronization, declaration hover, and same-document definition navigation.
- [x] Live LSP syntax diagnostics, declaration hover, and same-document definition navigation.
- [x] Bounded cross-document declaration navigation plus DWARF locals, aggregates, optimized builds, and panic/backtrace debugger tests.
- [x] Compiler-backed live diagnostics, incremental syntax trees, completion, signatures, references, and workspace rename.
- [x] Compiler-resolved inferred-variable/value/field hover and exact local/global/field definition spans.
- [x] Package navigation/completion, unused-use quick fixes, rich aggregate hover, semantic tokens,
      symbols, formatting, inlay hints, named call snippets, and source-mapped diagnostics.
- [x] TCP WebSocket echo application with masking-role, close-code/reason, and fragmented UTF-8 validation.
- [x] SDL3 swapchain clear/present application plus explicit queued-audio controls.
- [x] Stability, ownership, security-boundary, project, benchmark, and support documentation refreshed.
- [x] Deterministic compiler/parser/C-binding fuzz smoke, artifact replay, and debug/release differential checks.
- [x] Nightly four-seed sanitized 20,000-case fuzz sweep with failing-corpus artifact retention.
- [ ] Production soak evidence accumulates only from real scheduled runs and applications.

“Complete” means implemented and validated, not merely expressible through C or cross-linked from Linux.
