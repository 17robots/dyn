# vendor/curl

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/vendor-packages/curl/main.dyn](../../tests/vendor-packages/curl/main.dyn)

Reviewed behavioral fixtures: [tests/vendor-packages.py](../../tests/vendor-packages.py), [tests/vendor-packages/curl/main.dyn](../../tests/vendor-packages/curl/main.dyn)

## Declarations and source contracts

## Source: compiler/vendor/curl/curl.dyn

[Source](../../compiler/vendor/curl/curl.dyn#L5)

```dyn
pub struct Result { written: usize, code: i32, http_status: c.long, capacity_exceeded: bool, ok: bool }
```

[Source](../../compiler/vendor/curl/curl.dyn#L8)

Call once before starting worker threads; cleanup only after all transfers end.

```dyn
pub fn init() i32
```

[Source](../../compiler/vendor/curl/curl.dyn#L9)

```dyn
pub fn cleanup()
```

[Source](../../compiler/vendor/curl/curl.dyn#L27)

Synchronous HTTP(S) GET. URL copied through caller scratch; response goes into
caller storage. TLS verification remains enabled. Redirects are not followed.
HTTP error responses still have ok=true if transport succeeds; inspect status.
On failure written bytes are partial, not a complete response. No borrows escape.

```dyn
pub fn get_into(url: []const u8, url_buffer: []u8, destination: []u8, timeout_ms: i32) Result
```
