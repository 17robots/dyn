# std/net/tls

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-tls-native/main.dyn](../../tests/sdk-tls-native/main.dyn)
- [tests/sdk-tls/main.dyn](../../tests/sdk-tls/main.dyn)
- [tests/stdlib-tls/main.dyn](../../tests/stdlib-tls/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/net/tls/tls.dyn

[Source](../../compiler/std/net/tls/tls.dyn#L5)

```dyn
pub type Context = provider.Context
```

[Source](../../compiler/std/net/tls/tls.dyn#L6)

```dyn
pub type Connection = provider.Connection
```

[Source](../../compiler/std/net/tls/tls.dyn#L7)

```dyn
pub type Certificate = provider.Certificate
```

[Source](../../compiler/std/net/tls/tls.dyn#L8)

```dyn
pub type ErrorKind = provider.ErrorKind
```

[Source](../../compiler/std/net/tls/tls.dyn#L9)

```dyn
pub type ContextResult = provider.ContextResult
```

[Source](../../compiler/std/net/tls/tls.dyn#L10)

```dyn
pub type ConnectionResult = provider.ConnectionResult
```

[Source](../../compiler/std/net/tls/tls.dyn#L11)

```dyn
pub type Result = provider.Result
```

[Source](../../compiler/std/net/tls/tls.dyn#L13)

```dyn
pub fn set_alpn_protocols(connection: Connection, protocols: []const u8) bool
```

[Source](../../compiler/std/net/tls/tls.dyn#L14)

```dyn
pub fn selected_alpn(connection: Connection) []const u8
```

[Source](../../compiler/std/net/tls/tls.dyn#L15)

```dyn
pub fn peer_certificate_owned(connection: Connection) Certificate
```

[Source](../../compiler/std/net/tls/tls.dyn#L16)

```dyn
pub fn certificate_free_owned(certificate: Certificate)
```

[Source](../../compiler/std/net/tls/tls.dyn#L17)

```dyn
pub fn certificate_subject(destination: []u8, certificate: Certificate) []u8
```

[Source](../../compiler/std/net/tls/tls.dyn#L18)

```dyn
pub fn handshake(connection: Connection) Result
```

[Source](../../compiler/std/net/tls/tls.dyn#L19)

```dyn
pub fn server_handshake(connection: Connection) Result
```

[Source](../../compiler/std/net/tls/tls.dyn#L20)

```dyn
pub fn read(connection: Connection, destination: []u8) Result
```

[Source](../../compiler/std/net/tls/tls.dyn#L21)

```dyn
pub fn write(connection: Connection, source: []const u8) Result
```

[Source](../../compiler/std/net/tls/tls.dyn#L22)

```dyn
pub fn shutdown(connection: Connection) bool
```

[Source](../../compiler/std/net/tls/tls.dyn#L23)

```dyn
pub fn error_code(connection: Connection, provider_result: i32) i32
```

[Source](../../compiler/std/net/tls/tls.dyn#L24)

```dyn
pub fn error_string(destination: []u8, code: u64) []u8
```

[Source](../../compiler/std/net/tls/tls.dyn#L26)

```dyn
pub fn client_config_create() ContextResult
```

[Source](../../compiler/std/net/tls/tls.dyn#L27)

```dyn
pub fn server_config_create(
  arena: *memory.Arena,
  certificate: []const u8,
  key: []const u8,
) ContextResult
```

[Source](../../compiler/std/net/tls/tls.dyn#L34)

```dyn
pub fn server_config_create_into(certificate: []const u8, key: []const u8, certificate_storage: []u8, key_storage: []u8) ContextResult
```

[Source](../../compiler/std/net/tls/tls.dyn#L35)

```dyn
pub fn config_destroy(context: Context)
```

[Source](../../compiler/std/net/tls/tls.dyn#L36)

```dyn
pub fn client_connection_create(
  arena: *memory.Arena,
  context: Context,
  descriptor: i32,
  hostname: []const u8,
) ConnectionResult
```

[Source](../../compiler/std/net/tls/tls.dyn#L44)

```dyn
pub fn client_connection_create_into(context: Context, descriptor: i32, hostname: []const u8, storage: []u8) ConnectionResult
```

[Source](../../compiler/std/net/tls/tls.dyn#L45)

```dyn
pub fn server_connection_create(context: Context, descriptor: i32) ConnectionResult
```

[Source](../../compiler/std/net/tls/tls.dyn#L48)

```dyn
pub fn connection_destroy(connection: Connection)
```

[Source](../../compiler/std/net/tls/tls.dyn#L70)

Blocking I/O adapters borrow the Connection slot and its live handle.
Use read/write directly for nonblocking WantRead/WantWrite handling.

```dyn
pub fn reader(connection: *Connection) stream.Reader
```

[Source](../../compiler/std/net/tls/tls.dyn#L74)

```dyn
pub fn writer(connection: *Connection) stream.Writer
```
