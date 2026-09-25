# std/net/http

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/net-protocol/main.dyn](../../tests/net-protocol/main.dyn)
- [tests/sdk-hardening/main.dyn](../../tests/sdk-hardening/main.dyn)
- [tests/sdk-http-workers/main.dyn](../../tests/sdk-http-workers/main.dyn)
- [tests/sdk-web/main.dyn](../../tests/sdk-web/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/net/http/http.dyn

[Source](../../compiler/std/net/http/http.dyn#L7)

```dyn
pub type StreamReader = stream.Reader
```

[Source](../../compiler/std/net/http/http.dyn#L8)

```dyn
pub type StreamWriter = stream.Writer
```

[Source](../../compiler/std/net/http/http.dyn#L9)

```dyn
pub type StreamResult = stream.Result
```

[Source](../../compiler/std/net/http/http.dyn#L10)

```dyn
pub type Listener = network.Listener
```

[Source](../../compiler/std/net/http/http.dyn#L11)

```dyn
pub type Connection = network.Connection
```

[Source](../../compiler/std/net/http/http.dyn#L13)

```dyn
pub struct AcceptResult { connection: Connection, error: isize, ok: bool }
```

[Source](../../compiler/std/net/http/http.dyn#L15)

```dyn
pub fn accept(listener: *Listener) AcceptResult
```

[Source](../../compiler/std/net/http/http.dyn#L19)

```dyn
pub fn close(connection: *Connection) isize
```

[Source](../../compiler/std/net/http/http.dyn#L24)

```dyn
pub enum Framing { None, Length, Chunked, Close }
```

[Source](../../compiler/std/net/http/http.dyn#L25)

```dyn
pub struct HttpHead {
  framing: Framing,
  code: u16,
  header_length: usize,
  content_length: usize,
  keep_alive: bool,
  chunked: bool,
  ok: bool,
}
```

[Source](../../compiler/std/net/http/http.dyn#L34)

```dyn
pub struct HttpHeader { name: []const u8, value: []const u8, ok: bool }
```

[Source](../../compiler/std/net/http/http.dyn#L35)

```dyn
pub struct Url { scheme: []const u8, host: []const u8, port: u16, target: []const u8, secure: bool, ok: bool }
```

[Source](../../compiler/std/net/http/http.dyn#L37)

```dyn
pub struct HttpIoResult {
  consumed: usize,
  count: usize,
  error: isize,
  ok: bool,
}
```

[Source](../../compiler/std/net/http/http.dyn#L59)

```dyn
pub fn write_request(destination: []u8, method: []const u8, target: []const u8, host: []const u8, body: []const u8) []u8
```

[Source](../../compiler/std/net/http/http.dyn#L74)

```dyn
pub fn write_response(destination: []u8, code: u16, reason: []const u8, content_type: []const u8, body: []const u8) []u8
```

[Source](../../compiler/std/net/http/http.dyn#L205)

```dyn
pub fn parse_response(input: []const u8) HttpHead
```

[Source](../../compiler/std/net/http/http.dyn#L206)

```dyn
pub fn parse_request(input: []const u8) HttpHead
```

[Source](../../compiler/std/net/http/http.dyn#L208)

```dyn
pub fn header(input: []const u8, name: []const u8) HttpHeader
```

[Source](../../compiler/std/net/http/http.dyn#L282)

Validate before decoding, so incomplete in-place input remains unchanged.

```dyn
pub fn decode_chunked(input: []const u8, destination: []u8) HttpIoResult
```

[Source](../../compiler/std/net/http/http.dyn#L289)

```dyn
pub fn parse_url(input: []const u8) Url
```

[Source](../../compiler/std/net/http/http.dyn#L327)

```dyn
pub const StatusOk: u16 = 200
```

[Source](../../compiler/std/net/http/http.dyn#L328)

```dyn
pub const StatusNoContent: u16 = 204
```

[Source](../../compiler/std/net/http/http.dyn#L329)

```dyn
pub const StatusBadRequest: u16 = 400
```

[Source](../../compiler/std/net/http/http.dyn#L330)

```dyn
pub const StatusNotFound: u16 = 404
```

[Source](../../compiler/std/net/http/http.dyn#L331)

```dyn
pub const StatusPayloadTooLarge: u16 = 413
```

[Source](../../compiler/std/net/http/http.dyn#L332)

```dyn
pub const StatusInternalServerError: u16 = 500
```

[Source](../../compiler/std/net/http/http.dyn#L334)

```dyn
pub enum ErrorKind { None, End, Invalid, Capacity, Io }
```

[Source](../../compiler/std/net/http/http.dyn#L336)

```dyn
pub struct Request {
  raw: []const u8,
  method: []const u8,
  target: []const u8,
  body: []const u8,
  header_length: usize,
  keep_alive: bool,
}
```

[Source](../../compiler/std/net/http/http.dyn#L345)

```dyn
pub struct Response {
  output: stream.Writer,
  started: bool,
  finished: bool,
}
```

[Source](../../compiler/std/net/http/http.dyn#L351)

```dyn
pub struct ResponseOptions {
  status: u16,
  reason: []const u8,
  content_type: []const u8,
  close_connection: bool,
}
```

[Source](../../compiler/std/net/http/http.dyn#L358)

```dyn
pub struct Server {
  input: stream.Reader,
  output: stream.Writer,
  storage: []u8,
  used: usize,
  consumed: usize,
}
```

[Source](../../compiler/std/net/http/http.dyn#L366)

```dyn
pub struct ReceiveResult {
  request: Request,
  response: Response,
  error: ErrorKind,
  system_error: isize,
  ok: bool,
}
```

[Source](../../compiler/std/net/http/http.dyn#L374)

```dyn
pub struct Result {
  error: ErrorKind,
  system_error: isize,
  ok: bool,
}
```

[Source](../../compiler/std/net/http/http.dyn#L380)

```dyn
pub struct Body {
  output: stream.Writer,
  finished: bool,
}
```

[Source](../../compiler/std/net/http/http.dyn#L385)

```dyn
pub struct BodyResult {
  body: Body,
  result: Result,
  ok: bool,
}
```

[Source](../../compiler/std/net/http/http.dyn#L391)

```dyn
pub type Handler = *fn(*Response, *const Request) Result
```

[Source](../../compiler/std/net/http/http.dyn#L393)

```dyn
pub struct Route {
  method: []const u8,
  target: []const u8,
  handler: Handler,
}
```

[Source](../../compiler/std/net/http/http.dyn#L399)

```dyn
pub struct Router {
  routes: []Route,
  count: usize,
  fallback: Handler,
}
```

[Source](../../compiler/std/net/http/http.dyn#L405)

```dyn
pub struct ClientResponse {
  raw: []u8,
  body: []u8,
  status: u16,
  error: ErrorKind,
  system_error: isize,
  ok: bool,
}
```

[Source](../../compiler/std/net/http/http.dyn#L416)

Router storage is supplied by the caller. Route strings are borrowed.

```dyn
pub fn router(storage: []Route, fallback: Handler) Router
```

[Source](../../compiler/std/net/http/http.dyn#L420)

```dyn
pub fn route(state: *Router, method: []const u8, target: []const u8, handler: Handler) bool
```

[Source](../../compiler/std/net/http/http.dyn#L427)

```dyn
pub fn dispatch(state: *Router, response: *Response, request: *const Request) Result
```

[Source](../../compiler/std/net/http/http.dyn#L440)

```dyn
pub fn server(input: stream.Reader, output: stream.Writer, storage: []u8) Server
```

[Source](../../compiler/std/net/http/http.dyn#L444)

```dyn
pub fn connection_server(input: stream.Reader, output: stream.Writer, storage: []u8) Server
```

[Source](../../compiler/std/net/http/http.dyn#L482)

Returned request slices borrow state.storage and remain valid only until the next receive call.

```dyn
pub fn receive(state: *Server) ReceiveResult
```

[Source](../../compiler/std/net/http/http.dyn#L580)

```dyn
pub fn respond(response: *Response, body: []const u8, options: ResponseOptions) Result
```

[Source](../../compiler/std/net/http/http.dyn#L588)

```dyn
pub fn respond_stream(response: *Response, options: ResponseOptions) BodyResult
```

[Source](../../compiler/std/net/http/http.dyn#L633)

```dyn
pub fn body_writer(body: *Body) stream.Writer
```

[Source](../../compiler/std/net/http/http.dyn#L637)

```dyn
pub fn body_finish(body: *Body) Result
```

[Source](../../compiler/std/net/http/http.dyn#L644)

```dyn
pub fn body_abort(body: *Body) Result
```

[Source](../../compiler/std/net/http/http.dyn#L649)

```dyn
pub fn serve_connection(connection: *network.Connection, storage: []u8, handler: Handler) Result
```

[Source](../../compiler/std/net/http/http.dyn#L654)

Stream seam shared by plain TCP, TLS, tests, and embedded transports.

```dyn
pub fn serve_stream(input: stream.Reader, output: stream.Writer, storage: []u8, handler: Handler) Result
```

[Source](../../compiler/std/net/http/http.dyn#L672)

Performs one bounded HTTP/1.1 exchange over any stream pair. This is the HTTPS
integration point: pass a TLS reader and writer. Returned slices borrow response_storage.

```dyn
pub fn client_do(input: stream.Reader, output: stream.Writer, request_storage: []u8, response_storage: []u8,
  method: []const u8, target: []const u8, host: []const u8, body: []const u8) ClientResponse
```

[Source](../../compiler/std/net/http/http.dyn#L723)

```dyn
pub fn client_do_connection(connection: *network.Connection, request_storage: []u8, response_storage: []u8,
  method: []const u8, target: []const u8, host: []const u8, body: []const u8) ClientResponse
```
