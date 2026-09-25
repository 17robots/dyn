# Application standard library

Low-level application APIs never allocate implicitly. Linux exposes the broadest syscall surface;
Windows and macOS adapters cover core file, memory, socket, and event operations.

- `std/fs`, `std/path`, `std/os/linux`: files, paths, processes, environment, pipes, and explicit platform operations.
- `std/net`: typed IPv4 TCP/UDP addresses, bind/connect/listen/accept, send/receive, socket reuse, nonblocking mode, polling/timeouts, shutdown/close; a procedural event queue with caller-owned storage; caller-buffer DNS, HTTP/1, and strict WebSocket frame codecs. WebSocket payloads borrow input; handshake policy and masking entropy remain caller-owned.
- `std/flags`: long options, grouped short flags, attached short values, defaults, required options, occurrence counts, and positionals. Result storage comes from caller slices; strings remain borrowed.
- `std/encoding/json`: allocation-free validation/string escaping, arena-backed DOM parsing, object/array access, and DOM writing into caller buffer. Parsed number spellings borrow source; decoded strings and nodes live in caller arena.
- `std/io`: borrowed reader/writer callbacks and composable stream operations.
- `std/terminal`: standard streams and terminal control; `std/log`: logging to an explicit writer.
- `std/fmt`: formatting into caller-owned buffers; no writer interface or hidden allocation.
- `std/testing`: panic-based byte/integer expectations and caller-buffer temporary paths.
- `std/net/tls`: OpenSSL-backed client contexts/connections with default roots, peer and hostname verification, SNI, caller-buffer I/O, and explicit provider ownership/linking.
- `vendor/sdl3` (optional): automatically linked window/renderer/input, queued-audio control, and GPU swapchain/render-pass primitives with SDL-owned handles.

Syscall failures return negative Linux error numbers in `error`; `ok` indicates success. File paths use bounded 4096-byte stack scratch and return `-36` when too long. Retained path construction must use caller storage via `path.join`.

The event queue is implemented and compile-tested for both Linux architectures. Call
`net.nonblocking`, register a descriptor with `net.event_add`, and pass caller-owned
`[]net.Event` storage to `net.event_wait`; `event_modify` and `event_remove` update its
lifecycle. A returned event exposes readiness flags and the exact `u64` data supplied at
registration. The wait retries interrupted syscalls and rejects empty output storage.
Darwin and Windows use `std/os/macos` and `std/os/windows` adapters; their smaller surface is kept distinct from
Linux-only syscall packages.

DNS resolver requires caller-selected DNS server, packet scratch, and result storage. HTTP helper is
plain HTTP/1; applications may layer `std/net/tls` over connected sockets. Complete chunked bodies can
be decoded into caller storage; redirect policy remains application-owned. `std/thread` provides Linux
x86-64 and AArch64 caller-stack threads; `std/sync` provides futex synchronization and sequentially consistent atomics.

The allocation-free WebSocket codec validates RFC 6455 upgrade request/response headers, computes
`Sec-WebSocket-Accept` with internal fixed SHA-1 scratch, and writes the server 101 response into
caller storage. Its state machine assembles fragments, handles interleaved controls, validates text
and close-reason UTF-8/status codes, and optionally enforces endpoint masking roles. Parsed keys and
frame payloads borrow input. Header token-list negotiation and
extensions/subprotocol policy remain application-owned.
