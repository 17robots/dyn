# Supported format and platform boundaries

These are intentional scope limits, not requests to add features before 0.1.
Package-specific documents and source contracts define exact capacities/results.

| Surface | Included | Outside current promise |
| --- | --- | --- |
| HTTP | HTTP/1 framing, chunked/close-delimited bodies, bounded stream operations | HTTP/2, HTTP/3, automatic redirect policy |
| DNS | A/AAAA answers, bounded caller storage, TCP fallback | DNSSEC, recursive cache, iterative resolution, IPv6 DNS-server transport |
| TLS | OpenSSL 3 client/server on Linux, peer/hostname verification | Native macOS/Windows TLS adapters, OpenSSL 1.1.1 |
| WebSocket | Upgrade/frame checks, fragments, controls, UTF-8, masking-role checks | Automatic extension/subprotocol policy or hidden entropy source |
| ZIP | Checked ZIP32 directory/local relationships, descriptors, CRC, supported codecs | ZIP64 and encryption |
| TAR | Plain headers, PAX/GNU long-name metadata, caller-backed streaming | Sparse extraction and base-256 numbers |
| XML | Scanner/writer, CDATA, Unicode names, namespace context | DTD/external entity expansion or a validating XML processor |
| Unicode | Generated case/normalization/grapheme tables and explicit byte storage | Locale-sensitive collation or automatic normalization of strings |
| Process | Explicit child lifecycle, pipes, bounded capture and direct-child cleanup | Automatic process-tree termination |
| Threads | Linux x86-64/AArch64 caller-stack lifecycle and sync primitives | Portable Windows/macOS implementation, detach/cancellation/language TLS |
| Conservative `dyn-bind` generator | Representable scalars, pointers and C-compatible structs; JSON omission reports and C/Dyn layout probes | Unions, bitfields, preprocessing or arbitrary C declarators; cross-linking does not verify runtime layout |

Unsupported encodings/variants must return the documented failure, without
unbounded allocation, hangs or out-of-bounds writes. Partial output is allowed
only where the package contract says so. Input/output aliasing and retained
lifetimes follow `docs/buffer-contracts.md` and `docs/memory.md`.

The separate raw vendor generator supports unions/bitfields through C adapters
and provides selected value-taking macro helpers; see
[raw vendor bindings](../vendor-raw-bindings.md) for its qualified scope.
