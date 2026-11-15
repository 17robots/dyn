# Web applications

This guide builds a web application on `std/net/http/evented`: routing,
sessions, passwords, JSON, static files, slow work, live updates, limits and
shutdown. Each section names the std pieces and the costs they carry. The
`projects/webapp-eval` Chirp app uses all of them.

## The server

`evented` runs one event loop per worker thread over many nonblocking
keep-alive connections. All memory is fixed at start from one arena:
`evented.storage_size(config, workers)` says how much. Handlers have the
ordinary `http.Handler` shape and run on the worker that owns the connection.

```dyn
use "std/mem"
use "std/net"
use "std/net/http"
use "std/net/http/evented"

struct App {
  router: http.Routes(App),
  routes: [16]http.TypedRoute(App),
}

fn health(response: *http.Response, request: *const http.Request, app: *App) http.Result {
  return http.respond(response, "ok\n", http.ResponseOptions{ content_type: "text/plain" })
}

fn handle(response: *http.Response, request: *const http.Request, app: *App) http.Result {
  return http.serve_routes(&app.router, response, request)
}

fn serve(app: *App, workers: []evented.Worker) {
  app.router = http.typed_routes(app.routes[..], app)
  _ = http.add(&app.router, "GET", "/health", health)
  typed := http.Typed(App){ state: app, handler: handle }
  binding := http.bind(&typed)
  config := evented.default_config()
  arena := mem.arena_alloc(evented.storage_size(config, #len(workers)) + mem.MiB)
  _ = evented.start_shared(arena, workers, net.ipv4(127, 0, 0, 1, 8080), 1024, config, binding.handler, binding.context)
}
```

Routes match exact paths with `:name` segments (`/posts/:id`, read with
`http.param`). A path that matches with another method gets 405 with `Allow`.
A `GET` route also answers `HEAD`: the response sends its head, with the
`Content-Length` the body would have, and drops the body.

Every response carries `Date`, formatted once per loop pass by the server.
`1xx`, `204` and `304` heads carry no `Content-Type` or `Content-Length`, and
`respond` rejects a body for them.

## Sessions and CSRF

Read cookies with `http.cookie(request, "sid")`; write them with
`http.set_cookie` into caller storage, then pass the text as a `Set-Cookie`
header:

```dyn
use "std/net/http"

fn session_header(storage: []u8, token: []const u8) http.Header {
  text := http.set_cookie(storage, http.Cookie{ name: "sid", value: token, path: "/", max_age: 86400,
    http_only: true, secure: true, same_site: http.SameSite.Lax })
  return http.Header{ name: "Set-Cookie", value: text.value }
}
```

`set_cookie` refuses names that are not tokens, values outside the cookie
octets, attributes with `;` or control bytes, and `SameSite=None` without
`Secure`. A negative `max_age` deletes the cookie.

Make session tokens with `std/crypto/random` (32 bytes, hex). Pair each
session with a CSRF token and require it on every state-changing request, in
a form field or an `X-CSRF-Token` header, compared with
`crypto_core.equal_constant_time`. `SameSite=Lax` blocks most cross-site
posts; the token covers the rest.

## Passwords

Store passwords with Argon2id from `std/crypto/password`. It is memory-hard,
so it needs a workspace: `argon2id_workspace_words(parameters)` u64 words,
about 19 MiB for `Argon2Recommended` (OWASP's first configuration). Store the
PHC string from `argon2id_encode` and check logins with `argon2id_verify`,
which reads the parameters back from the string.

A hash takes tens of milliseconds. Never run it on the event loop: every
other connection on that worker would wait. Hand it to a pool with `run`.

## Slow work: run

`evented.run` gives the request to a `std/thread/pool` pool. The work
function runs on a pool thread; the finish function answers on the worker
thread with a fresh response and the same request. The handler returns at
once, and the connection reads nothing until finish has run. Job data lives
in per-connection storage from `evented.job` (`Config.job_size` bytes):

```dyn
use "std/crypto/password"
use "std/io"
use "std/mem"
use "std/net/http"
use "std/net/http/evented"

struct Login { password: [128]u8, length: usize, encoded: [128]u8, encoded_length: usize, valid: bool }

fn check(job: *Login) {
  // A pool thread: allocate the workspace per job, or keep one per pool thread.
  _ = job
}

fn answer(response: *http.Response, request: *const http.Request, job: *Login) http.Result {
  if !job.valid {
    return http.respond(response, "bad credentials\n", http.ResponseOptions{ status: http.StatusUnauthorized })
  }
  return http.respond(response, "welcome\n", http.ResponseOptions{})
}

fn login(response: *http.Response, request: *const http.Request) http.Result {
  job := evented.job(Login, response)
  if job == nil || #len(request.body) > #len(job.password) {
    return http.respond(response, "too large\n", http.ResponseOptions{ status: http.StatusPayloadTooLarge })
  }
  job.length = mem.copy(job.password[..], request.body)
  if io.failed(evented.run(response, job, check, answer)) {
    return http.respond(response, "busy\n", http.ResponseOptions{ status: http.StatusServiceUnavailable })
  }
  return http.Result{}
}
```

Work that calls C libraries, such as SQLite, needs a pool on threads with
libc state: `pool.start_spawned(arena, threads, capacity, stack, &posix.spawner())`.
Pass it as `Config.pool`. `join` waits for running jobs.

## JSON

`std/encoding/json` parses into an arena (`json.parse`) and writes into
caller storage without a tree (`json.writer`). The writer places commas
itself; failure is sticky, so check once:

```dyn
use "std/encoding/json"

fn post_json(storage: []u8, id: i64, author: []const u8, body: []const u8) []const u8 {
  out := json.writer(storage)
  json.object_begin(&out)
  json.key(&out, "id")
  json.integer(&out, id)
  json.key(&out, "author")
  json.text(&out, author)
  json.key(&out, "body")
  json.text(&out, body)
  json.object_end(&out)
  return json.output(&out)
}
```

`json.output` is empty when anything failed: storage too small, invalid
UTF-8, a value without its key, or a container left open.

## HTML

`std/html` escapes text by default; raw markup must be marked with
`html.trusted`. Render into transport storage with `http.body_buffer` and
`http.respond_buffered` to skip a copy.

## Static files

`http.make_asset` wraps bytes (from `#load` or a file) as an `Asset`: content
type from the extension, a strong ETag, and a gzip copy at level 9 when that
is smaller. `http.load_directory` loads a whole tree at startup.
`http.serve_asset` answers `If-None-Match` and `If-Modified-Since` with 304,
sends gzip when `Accept-Encoding` allows it (q-values honored), and sets
`Vary`, `ETag`, `Last-Modified` and the `Cache-Control` you give. A single
`Range` gets 206 with the uncompressed bytes, honoring `If-Range`; a range
past the end gets 416. Fingerprinted
names can use `"public, max-age=31536000, immutable"`.

For dynamic responses, `gzip.write` compresses into caller storage
with a reusable `gzip.Encoder` workspace. Level 1 is fast; level 6 matches
zlib's default size.

## Forms and uploads

`http.form_value` decodes urlencoded fields. `http.multipart` and
`http.next_part` walk a `multipart/form-data` body; parts borrow it. A request
larger than `Config.receive_size` borrows one of `Config.upload_count` blocks
of `Config.upload_size` bytes until it is handled (503 when none is free, 413
when it is bigger). Clients that send `Expect: 100-continue` get `100 Continue`
before their body.

## Live updates

`evented.open_stream` starts a chunked response that stays open after the
handler returns, such as `text/event-stream`; format events with
`http.sse_event`. `evented.upgrade` switches a request to a WebSocket. Both
return a `Peer`, valid from any thread:

- `evented.send(workers, peer, payload, binary)` queues one message.
- `evented.publish(workers, topic, payload, binary)` reaches every stream and
  socket opened with that topic, on every worker.
- `evented.close_peer(workers, peer)` ends a stream or sends a close frame.

Messages pass through each worker's inbox (`Config.inbox_messages`,
`Config.inbox_bytes`); a full inbox fails the post, so the caller decides
what to drop. WebSocket messages from clients arrive at `Config.on_message`
on the worker thread, with `Config.message_context`. Pings are answered and
client closes echoed. A peer too slow to take a message is closed instead of
blocking the worker.

## Limits

When every slot of a worker is busy, a new client first evicts the longest
idle keep-alive connection idle at least `Config.evict_idle_milliseconds`.
Otherwise `Overflow.Wait` holds it in a reserve slot until a regular one
frees, and `Overflow.Reject` answers 503 with `Retry-After`. Requests larger
than the receive buffer get 413.

`http.Limiter` keeps token buckets per key, such as five logins a minute per
address: `http.allow(&limiter, http.ip_key(ip.bytes[..ip.length], 1))`, with
the client address from `evented.client_ip(response)`. Behind a proxy that is
the proxy; read `X-Forwarded-For` only from proxies you trust.

## SQLite

`vendor/sqlite` statements are prepared once and reused. Bind a whole
parameter list with `sqlite.bind_values(&statement, id, name, sqlite.Blob{ bytes: hash })`
and give the statement back with `defer sqlite.done(&statement)`, which resets
it and clears its bindings. With one connection shared by workers, open it
with `OpenOptions{ caller_serialized: true }` and hold your own mutex around
each use; copy column bytes out before the next step. See [sqlite.md](sqlite.md).

## Shutdown

Watch signals with `std/process/signal` on the main thread before starting
workers, then `signal.wait`, `evented.stop`, `evented.join`, and close the
database. Workers close their connections and wait for running jobs.

## TLS

`std/net/http/evented/tls` supplies an OpenSSL transport for `Config.transport`;
see [tls.md](tls.md). TLS clients cannot read a 503 before their handshake,
so with `Overflow.Reject` they are closed instead.

## Not yet

- HTTP/2 and HTTP/3.
- Unbounded streaming request bodies: a request must fit `Config.upload_size`.
- Chunked request bodies (`Transfer-Encoding: chunked` uploads) get 400.
- Response compression on the fly in `serve_asset`; dynamic responses call
  `gzip.write` themselves.
