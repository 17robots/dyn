# vendor/openssl/tls

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/vendor/openssl/tls/raw_generated.dyn

## Source: compiler/vendor/openssl/tls/tls.dyn

Target gate: `#target(kernel: linux)`

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L10)

OpenSSL 3 TLS adapter. OpenSSL owns Context/Connection allocations;
every successful create_owned call requires its matching free_owned call.
Network descriptors and all byte/name buffers remain caller-owned.

```dyn
pub type Context = rawptr
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L11)

```dyn
pub type Connection = rawptr
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L12)

```dyn
pub type Certificate = rawptr
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L14)

```dyn
pub enum ErrorKind {
  None,
  InvalidArgument,
  Provider,
  Verification,
  WantRead,
  WantWrite,
}
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L23)

```dyn
pub struct ContextResult { value: Context, error: ErrorKind, provider_code: u64, ok: bool }
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L24)

```dyn
pub struct ConnectionResult { value: Connection, error: ErrorKind, provider_code: u64, ok: bool }
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L25)

```dyn
pub struct Result { count: usize, error: ErrorKind, provider_code: u64, provider_status: i32, ok: bool }
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L49)

Loads provider-default trust roots and enables peer-certificate verification.

```dyn
pub fn context_create_owned() ContextResult
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L64)

```dyn
pub fn context_free_owned(context: Context)
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L69)

Creates a server context and loads PEM certificate chain/private key.

```dyn
pub fn server_context_create_owned(certificate: []const u8, key: []const u8,
                                   certificate_buffer: []u8, key_buffer: []u8) ContextResult
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L92)

The arena supplies temporary C strings only; OpenSSL owns the result.

```dyn
pub fn server_context_create(arena: *mem.Arena, certificate: []const u8, key: []const u8) ContextResult
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L101)

```dyn
pub fn server_connection_create_owned(context: Context, descriptor: i32) ConnectionResult
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L114)

protocols is OpenSSL wire format: one length byte followed by each protocol.
OpenSSL copies the bytes; the caller retains ownership.

```dyn
pub fn set_alpn_protocols(connection: Connection, protocols: []const u8) bool
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L127)

Returned selection borrows the connection and dies when it is freed or renegotiated.

```dyn
pub fn selected_alpn(connection: Connection) []const u8
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L137)

Caller owns the returned reference and must call certificate_free_owned.

```dyn
pub fn peer_certificate_owned(connection: Connection) Certificate
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L141)

```dyn
pub fn certificate_free_owned(certificate: Certificate)
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L144)

```dyn
pub fn certificate_subject(destination: []u8, certificate: Certificate) []u8
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L155)

Configures both certificate hostname verification and SNI. name_buffer must
fit hostname plus NUL and is only borrowed during this call.

```dyn
pub fn connection_create_owned(context: Context, descriptor: i32, hostname: []const u8, name_buffer: []u8) ConnectionResult
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L179)

```dyn
pub fn connection_create(arena: *mem.Arena, context: Context, descriptor: i32, hostname: []const u8) ConnectionResult
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L188)

```dyn
pub fn connection_free_owned(connection: Connection)
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L192)

```dyn
pub fn handshake(connection: Connection) Result
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L204)

```dyn
pub fn server_handshake(connection: Connection) Result
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L212)

```dyn
pub fn read(connection: Connection, destination: []u8) Result
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L227)

```dyn
pub fn write(connection: Connection, source: []const u8) Result
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L238)

May return false when provider requires another bidirectional shutdown call.

```dyn
pub fn shutdown(connection: Connection) bool
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L243)

```dyn
pub fn error_code(connection: Connection, provider_result: i32) i32
```

[Source](../../compiler/vendor/openssl/tls/tls.dyn#L249)

Writes provider message into caller buffer. Returned slice excludes NUL.

```dyn
pub fn error_string(destination: []u8, code: u64) []u8
```
