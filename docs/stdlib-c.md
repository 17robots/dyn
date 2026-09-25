# C interop

`std/c` gives C ABI types ordinary package names. It has no special import behavior,
header parser, ownership, or allocation. Bindings remain explicit `extern fn`
declarations.

```dyn
use "std/c" c

extern fn strlen(value: c.string) c.size
```

Scalar aliases select target ABI at compile time. `long` is pointer-width on Linux/macOS
LP64 targets and 32-bit on Windows x64 LLP64; `intptr`, `uintptr`, `intmax`, and `uintmax`
just width intent explicit. `pointer` aliases `rawptr`. No alias changes representation.

`c.string` is borrowed null-terminated storage. `string_from_bytes` copies into a
caller buffer and appends zero. It never allocates, supports overlap, and rejects
embedded zero bytes. Result errors distinguish invalid input, capacity and overflow;
`required` includes the terminator. Failure changes no bytes. `string_from_arena`
uses this implementation and rewinds its allocation on failure.

`string_length` and `bytes_from_string` require a caller-selected maximum, preventing
an unbounded foreign-memory scan. The returned byte slice borrows the C storage.
`errno_from_result` decodes Dyn's direct-syscall negative error convention; libc APIs
with thread-local `errno` still require an explicit binding. Dynamic loading is likewise
an optional platform/libc binding, not a mandatory dependency of the freestanding runtime.

Plain `c.char` follows the default target C ABI: `u8` on Linux AArch64, `i8` on
Linux x86-64, Windows x86-64 and macOS AArch64. Nondefault compiler char-signedness
flags require matching explicit bindings. `c.signed_char`/`c.unsigned_char` remain
`i8`/`u8`; the byte-oriented C string helpers continue using `u8` storage.
