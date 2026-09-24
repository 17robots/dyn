# std/net/websocket

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-web/main.dyn](../../tests/sdk-web/main.dyn)
- [tests/websocket/main.dyn](../../tests/websocket/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/net/websocket/websocket.dyn

[Source](../../compiler/std/net/websocket/websocket.dyn#L5)

```dyn
pub struct WebSocketFrame { payload: []const u8, opcode: u8, mask: u32, consumed: usize, final: bool, masked: bool, ok: bool }
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L6)

```dyn
pub struct WebSocketUpgrade { key: []const u8, ok: bool }
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L7)

```dyn
pub enum WebSocketEventKind { None, Ready, Ping, Pong, Close, Error }
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L8)

```dyn
pub struct WebSocketMessageState { used: usize, opcode: u8, fragmented: bool, closed: bool, enforce_mask: bool, masked: bool }
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L9)

```dyn
pub struct WebSocketEvent { payload: []u8, kind: WebSocketEventKind, opcode: u8, close_code: u16, ok: bool }
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L11)

```dyn
pub struct WebSocketConnection {
  input: http.StreamReader,
  output: http.StreamWriter,
  frames: []u8,
  message: []u8,
  control: []u8,
  state: WebSocketMessageState,
  client: bool,
}
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L21)

```dyn
pub struct WebSocketResult {
  event: WebSocketEvent,
  error: isize,
  ok: bool,
}
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L352)

Concise public names; websocket_* spellings remain as compatibility aliases.

```dyn
pub fn accept(destination: []u8, key: []const u8) []u8
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L356)

```dyn
pub fn validate_upgrade_request(request: []const u8) WebSocketUpgrade
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L360)

```dyn
pub fn write_upgrade_response(destination: []u8, key: []const u8) []u8
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L364)

```dyn
pub fn validate_upgrade_response(response: []const u8, key: []const u8) bool
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L368)

```dyn
pub fn write_frame(destination: []u8, opcode: u8, payload: []const u8, final: bool, masked: bool, mask: u32) []u8
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L372)

```dyn
pub fn parse_frame(input: []const u8) WebSocketFrame
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L373)

```dyn
pub fn decode_frame(destination: []u8, frame: WebSocketFrame) []u8
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L374)

```dyn
pub fn message_state(expect_masked: bool) WebSocketMessageState
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L375)

```dyn
pub fn receive(state: *WebSocketMessageState, message: []u8, control: []u8, frame: WebSocketFrame) WebSocketEvent
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L381)

Stateful stream wrapper. All buffers are caller-owned; client controls require
a fresh unpredictable mask supplied to connection_send.

```dyn
pub fn connection(input: http.StreamReader, output: http.StreamWriter, frames: []u8, message: []u8,
  control: []u8, client: bool) WebSocketConnection
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L394)

```dyn
pub fn connection_send(state: *WebSocketConnection, opcode: u8, payload: []const u8, final: bool, mask: u32) isize
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L402)

```dyn
pub fn connection_ping(state: *WebSocketConnection, payload: []const u8, mask: u32) isize
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L406)

```dyn
pub fn connection_pong(state: *WebSocketConnection, payload: []const u8, mask: u32) isize
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L410)

```dyn
pub fn connection_close(state: *WebSocketConnection, payload: []const u8, mask: u32) isize
```

[Source](../../compiler/std/net/websocket/websocket.dyn#L414)

```dyn
pub fn connection_receive(state: *WebSocketConnection) WebSocketResult
```
