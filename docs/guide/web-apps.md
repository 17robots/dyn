# Web applications

This guide builds a web application on `std/net/http/evented`: routing,
sessions, passwords, JSON, static files, slow work, live updates, limits and
shutdown. Each section names the std pieces and the costs they carry. The
`projects/webapp-eval` Chirp app uses all of them.

## The server

`evented` runs one event loop per worker thread over many nonblocking
keep-alive connections. All memory is fixed at start from one arena:
`evented.storage_size(config, workers)` says how much. Each worker's share is
one block marked `mem.advise_sparse`: buffers cost memory only when used,
even where the kernel would otherwise back them with 2 MiB huge pages. Handlers have the
ordinary `http.Handler` shape and run on the worker that owns the connection.

```dyn
use "std/fail"
use "std/mem"
use "std/net"
use "std/net/http"
use "std/net/http/evented"

struct App {
  router: http.Routes(App),
  routes: [16]http.TypedRoute(App),
}

fn health(status: *fail.Status, response: *http.Response, request: *const http.Request, app: *App) {
  http.text(status, response, 200, "ok\n")
}

fn handle(status: *fail.Status, response: *http.Response, request: *const http.Request, app: *App) {
  http.serve_routes(status, &app.router, response, request)
}

fn run(status: *fail.Status, app: *App, workers: []evented.Worker) {
  app.router = http.typed_routes(app.routes[..], app)
  http.add(status, &app.router, "GET", "/health", health)
  typed := http.Typed(App){ state: app, handler: handle }
  binding := http.bind(&typed)
  config := evented.default_config()
  arena := mem.arena_alloc(evented.storage_size(config, #len(workers)) + mem.MiB)
  defer mem.arena_release(arena)
  // Serves until SIGINT or SIGTERM, then stops and joins the workers.
  evented.serve(arena, status, workers, net.ipv4(127, 0, 0, 1, 8080), config, binding.handler, binding.context)
}
```

`http.text`, `http.json` and `http.redirect` are the usual replies: plain
text, JSON with `Cache-Control: no-store`, and a 303 that can set cookies.
`http.respond` takes any status, type, headers and cookies
(`ResponseOptions.cookies`, a list of `http.Cookie`). `http.query_has(request,
"debug")` says whether the query names a parameter, with or without a value.

A handler that fails before it responds gets a `500 internal server error`
from the server, and the failure goes to `Config.access_log`; the connection
closes after. So a handler never has to answer its own failures: it passes
its status to every call, and the first failure ends the request. A second
response to the same request fails with `InvalidState`, "already responded".
`Config.on_too_large` and `Config.on_busy` replace the server's own 413 and
503 replies with your handlers, such as a JSON error body for an API.

Each worker has a request arena, reset before every request:
`evented.arena(response)` is scratch for a page, copied column text or a
parsed body, sized by `Config.request_arena_size` (1 MiB). Exhaustion
panics, so size it for the largest response you build there.
`evented.worker_index(response)` names the worker running a handler; give
each worker its own state, such as a database connection, and it needs no
lock, because a worker's handlers run one at a time.

Routes match exact paths with `:name` segments (`/posts/:id`, read with
`http.param`). A path that matches with another method gets 405 with `Allow`.
A `GET` route also answers `HEAD`: the response sends its head, with the
`Content-Length` the body would have, and drops the body.

Every response carries `Date`, formatted once per loop pass by the server.
`1xx`, `204` and `304` heads carry no `Content-Type` or `Content-Length`, and
`respond` rejects a body for them.

A handler records any failure in its `status`; the server then closes the
connection after the response. A response whose write fails is finished:
later writes fail with `InvalidState` rather than send a broken message.

`evented` is the one server. Outside it, `http.serve_stream` runs a handler
over any `io.Reader` and `io.Writer` pair, one request at a time on the
calling thread: for a single-threaded or embedded server, or a test.

## Sessions and CSRF

`std/net/http/session` handles cookie sessions in front of your own store,
such as a SQLite table:

```dyn
use "std/mem"
use "std/net/http"
use "std/net/http/session" sessions

// cache is this worker's; shared is one for the whole server.
fn current(cache: *sessions.Cache, shared: *sessions.Shared, request: *const http.Request, now: i64) sessions.Session {
  token := sessions.token(request)
  session := sessions.cached(cache, shared, token, now)
  if session.found || #len(token) == 0 { return session }
  // Look token up in the store; on a hit, keep the answer:
  // return sessions.remember(cache, token, user, csrf, name, expires)
  return session
}
```

`sessions.start(arena, &status, seconds)` makes a token, a CSRF secret and the
cookie (`sid`, HttpOnly, SameSite=Lax) for a new session to store: pass
`started.cookie` in `ResponseOptions.cookies` or to `http.redirect`. After
deleting one from the store, `sessions.forget(&shared)` empties every worker's
cache and returns the cookie that clears it.
`sessions.csrf_ok(&session, presented)` compares a form field or
`X-CSRF-Token` header in constant time; require it on every state-changing
request. `data` (up to 64 bytes) is yours, such as the user's name.

Underneath, `http.cookie` reads cookies, and `respond` writes each
`http.Cookie` as a `Set-Cookie` header (`http.set_cookie` formats one into a
buffer for other uses). It refuses names that are not tokens, values outside the cookie octets,
attributes with `;` or control bytes, and `SameSite=None` without `Secure`.
A negative `max_age` deletes the cookie.

## Passwords

Store passwords with Argon2id from `std/crypto/password`: about 13 ms for
the recommended setting, within 1.4 times of the SIMD reference C. It is memory-hard,
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
use "std/fail"
use "std/mem"
use "std/net/http"
use "std/net/http/evented"

struct Login { password: [128]u8, length: usize, encoded: [128]u8, encoded_length: usize, valid: bool }

fn check(job: *Login) {
  // A pool thread: allocate the workspace per job, or keep one per pool thread.
  _ = job
}

fn answer(status: *fail.Status, response: *http.Response, request: *const http.Request, job: *Login) {
  if !job.valid {
    http.respond(status, response, "bad credentials\n", http.ResponseOptions{ status: http.StatusUnauthorized })
    return
  }
  http.respond(status, response, "welcome\n", http.ResponseOptions{})
}

fn login(status: *fail.Status, response: *http.Response, request: *const http.Request) {
  job := evented.job(Login, response)
  if job == nil || #len(request.body) > #len(job.password) {
    http.respond(status, response, "too large\n", http.ResponseOptions{ status: http.StatusPayloadTooLarge })
    return
  }
  job.length = mem.copy(job.password[..], request.body)
  // A full pool queue fails the hand-off; answer 503 instead.
  handed: fail.Status
  evented.run(&handed, response, job, check, answer)
  if handed.failed {
    http.respond(status, response, "busy\n", http.ResponseOptions{ status: http.StatusServiceUnavailable })
  }
}
```

Work that calls C libraries, such as SQLite, needs a pool on threads with
libc state: `pool.start_spawned(arena, &status, threads, capacity, stack, &posix.spawner())`.
Pass it as `Config.pool`. `join` waits for running jobs.

## Grouping work: later

`evented.later(&status, response, data, finish)` answers a request after the worker
has handled every connection that is ready now, on the same thread, before
it waits again. Requests that arrive together can share work, such as one
database transaction for many writes: each handler queues its row and calls
`later`; the first `finish` of the pass commits them all, and each `finish`
then replies. `data` lives in job storage (`evented.job`), like `run`.
HTTP/2 and HTTP/3 streams get InvalidState, so call `finish` yourself there.
Chirp creates posts this way: 2.3 times as many per second, with a quarter
of the p99 latency.

## JSON

`std/encoding/json` parses into an arena (`json.parse`) and writes into
caller storage without a tree (`json.writer`). `json.object_of` writes a
struct as an object, each field by name, and `json.array_of` a slice of
them:

```dyn
use "std/encoding/json"

struct Post { id: i64, author: []const u8, body: []const u8 }

fn posts_json(storage: []u8, posts: []const Post) []const u8 {
  out := json.writer(storage)
  json.object_begin(&out)
  json.key(&out, "posts")
  json.array_of(&out, posts)
  json.object_end(&out)
  return json.output(&out)
}
```

Fields may be integers, floats, bool or text; a nested struct fails the
writer, so write it with `json.key` and its own `object_of`. For one-off
objects, `json.field` writes a key and a scalar value. The writer places
commas itself, and failure is sticky: `json.output` is empty when anything
failed (storage too small, invalid UTF-8, a value without its key, or a
container left open).

## HTML

`std/html` escapes text by default; raw markup must be marked with
`html.trusted`. `html.print` fills `{}` with escaped text, numbers, or
`Trusted` markup as it is:

```dyn
use "std/fail"
use "std/html"
use "std/mem"
use "std/net/http"

fn greet(status: *fail.Status, response: *http.Response, storage: []u8, name: []const u8) {
  out := http.page_writer(status, response, storage)
  html.print(&out, "<!doctype html><title>Hi</title><p>Hello, <b>{}</b>!</p>", name)
  http.page(status, response, 200, &out)
}
```

`http.page_writer` renders into the send buffer when it is free, so the page
goes out without a copy, and `http.page` sends it as HTML, not cached, with
`Content-Security-Policy: default-src 'self'` and `nosniff`. A page too large
for its storage fails the status, and the server answers 500.

## Static files

`http.assets_of(arena, "app.js", #load("static/app.js"), ...)` makes sorted
assets from path and body pairs; `http.find_asset` looks one up.
`http.make_asset` wraps bytes (from `#load` or a file) as an `Asset`: content
type from the extension, a strong ETag, and a gzip copy at level 9 when that
is smaller. `http.load_directory` loads a whole tree at startup.
`http.serve_asset` answers `If-None-Match` and `If-Modified-Since` with 304,
sends gzip when `Accept-Encoding` allows it (q-values honored), and sets
`Vary`, `ETag`, `Last-Modified` and the `Cache-Control` you give. A single
`Range` gets 206 with the uncompressed bytes, honoring `If-Range`; a range
past the end gets 416. Fingerprinted
names can use `"public, max-age=31536000, immutable"`.

For dynamic responses, set `Config.compress_level` (1 is fast, 6 matches
zlib's default size) and answer with `evented.respond_compressed(status, response,
request, body, options)`. It gzips straight into the send buffer when the
content type compresses, the body has at least `http.CompressMinimum` (1 KiB)
bytes, the client accepts gzip and the result is smaller, and sends `Vary:
Accept-Encoding`. Each worker keeps one encoder (about 300 KiB). Outside the
evented server, `http.respond_compressed` takes the encoder and level, and
`gzip.write` compresses into caller storage.

## Forms and uploads

`http.form_value` decodes urlencoded fields. `http.multipart` and
`http.next_part` walk a `multipart/form-data` body; parts borrow it. A request
larger than `Config.receive_size` borrows one of `Config.upload_count` blocks
of `Config.upload_size` bytes until it is handled (503 when none is free, 413
when it is bigger). Clients that send `Expect: 100-continue` get `100 Continue`
before their body. Chunked request bodies (`Transfer-Encoding: chunked`) are
decoded in place once complete.

Bodies larger than any block go to `Config.on_large_body` with the head
alone (nil answers 413). It answers from the head, or reads the body as it
arrives with `evented.receive_body(&status, response, data, chunk, finish)`:

```dyn
use "std/fail"
use "std/net/http"
use "std/net/http/evented"

struct Upload { count: usize }

fn piece(job: *Upload, bytes: []const u8) bool {
  job.count += #len(bytes)
  return job.count <= 100 * 1024 * 1024
}

fn done(status: *fail.Status, response: *http.Response, request: *const http.Request, job: *Upload, end: evented.BodyEnd) {
  if end != evented.BodyEnd.Complete {
    http.respond(status, response, "upload failed\n", http.ResponseOptions{ status: http.StatusBadRequest })
    return
  }
  http.respond(status, response, "stored\n", http.ResponseOptions{})
}

fn large_body(status: *fail.Status, response: *http.Response, request: *const http.Request) {
  job := evented.job(Upload, response)
  reading: fail.Status
  if job != nil {
    evented.receive_body(&reading, response, job, piece, done)
  }
  if job == nil || reading.failed {
    http.respond(status, response, "busy\n", http.ResponseOptions{ status: http.StatusServiceUnavailable })
  }
}
```

`chunk` runs on the worker thread for every piece that arrives, chunked
framing already removed (`http.ChunkReader` does that incrementally);
return false to stop. `finish` runs once with how the body ended
(`BodyEnd.Complete`, `Stopped`, `Invalid` or `Closed`); after anything but
`Complete` the connection closes once it has answered, and `Closed` sends
nothing but lets it clean up. It may hand slow work to `run` with the same
data. Large-body connections never hold an upload block, and the idle
timeout applies to them.

## Live updates

`evented.open_stream` starts a chunked response that stays open after the
handler returns, such as `text/event-stream`; format events with
`http.sse_event`. `evented.upgrade` switches a request to a WebSocket. Both
return a `Peer`, valid from any thread:

- `evented.send(&status, workers, peer, payload, binary)` queues one message.
- `evented.publish(&status, workers, topic, payload, binary)` reaches every stream and
  socket opened with that topic, on every worker.
- `evented.close_peer(&status, workers, peer)` ends a stream or sends a close frame.

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

`vendor/sqlite` keeps prepared statements in a per-connection cache keyed by
their SQL, and runs them in one call each. Open one connection per worker
and pick it with `evented.worker_index`; then no handler shares a statement.

```dyn
use "std/fail"
use "std/mem"
use "std/net/http"
use "std/net/http/evented"
use "vendor/sqlite"

struct Database { handle: sqlite.Database, statements: sqlite.Cache }

fn name_of(status: *fail.Status, databases: []Database, response: *http.Response, id: i64) []const u8 {
  statements := &databases[evented.worker_index(response)].statements
  lookup := sqlite.cached(status, statements, "SELECT name FROM user WHERE id=?1")
  if !sqlite.first(status, lookup, id) { return "" }
  defer sqlite.done(lookup)
  return sqlite.text(evented.arena(response), lookup, 0)
}
```

`sqlite.run(&status, statement, values...)` binds, steps to the end and
resets; a failure lands on the status, so `sqlite.constraint(&status.failure)`
tells a duplicate key from other errors. `first` stops at the first row,
`query` and `next` walk rows, and `integer`, `bytes` (borrowed) and `text`
(copied into an arena) read columns. Copy borrowed bytes before the next
step. See [sqlite.md](sqlite.md).

Every connection to the file can read at once, but only one can write. Give
the app one `sync.Mutex` and hold it around each write or transaction:
writers then take turns in microseconds. Without it they meet SQLite's file
lock, and `sqlite.open_schema`'s busy handler (`sqlite.busy_wait`, retrying
from 20 microseconds up to 1 millisecond apart) keeps them correct but slower:
Chirp's creates ran at 119k per second that way and 191k with the mutex.

## Caching across workers

Each worker can keep its own copy of something built from shared data, such
as a rendered list, without locks. `std/cache` keeps them current: the
writer calls `cache.changed(&app.posts)` after a write, and a worker checks
before using its copy.

```dyn
seen := cache.stale(&worker.posts, &app.posts)
if seen != 0 {
  // rebuild the worker's copy
  cache.rebuilt(&worker.posts, seen)
}
```

`seen` is read before the rebuild, so a write that lands during it leaves
the copy stale for the next request. The session cache works the same way.

## Logging

Set `Config.access_log` to a `log.Logger` and the server writes one line per
answered request: client, method, path, status and the microseconds spent in
the handler (and its finish, for `run` and `later`). `log.write` sends a line
in one write, so workers' lines do not interleave.

A handler that blocks (a slow query, file I/O, password hashing) stalls
every connection on its worker. Set `Config.slow_handler_microseconds` and
the server warns about each handler that runs that long, with method, path
and time, in the access log or on standard error; move that work to `run`.

## Shutdown

`evented.serve` watches SIGINT and SIGTERM, serves, then stops the workers
and waits for them: workers close their connections and wait for running
jobs. Close the database after it returns. On Linux every worker gets its
own `SO_REUSEPORT` listener; where the kernel cannot balance those (macOS,
Windows) the workers share one. To run more than the server, call
`signal.watch` on the main thread yourself, then `start_shared` (Linux) or
`start` with your own listener, `signal.wait`, `evented.stop` and
`evented.join`. Threads from `std/thread`
and `std/thread/posix` start with SIGINT, SIGTERM and SIGHUP blocked, so a
pool started earlier cannot take the signal.

## HTTP/2

Set `Config.http2` and every connection may speak HTTP/2 (RFC 9113): TLS
clients that pick `h2` through ALPN, which browsers do once
`https.offer_http2(&status, context)` offers it, and cleartext clients that start with
the connection preface (prior knowledge, as `curl --http2-prior-knowledge`
and reverse proxies do). Others keep HTTP/1.1 on the same port.

Each stream becomes an ordinary `http.Request` for the same handler, and the
response it writes goes out as HEADERS and DATA frames, so routing, sessions,
`respond_compressed`, `serve_asset`, `run`, `open_stream`, `receive_body`
and `upgrade` work unchanged, per stream: a slow job holds up only its own
stream. WebSockets ride an HTTP/2 stream as RFC 8441 describes: the server
advertises `SETTINGS_ENABLE_CONNECT_PROTOCOL`, the client's extended CONNECT
reaches the handler as an ordinary `GET` with `Upgrade: websocket`, and
`upgrade` answers 200 instead of 101. A socket's messages assemble in its
request slot, so they are limited to `receive_size`, as on HTTP/1.1.

```dyn
use "std/mem"
use "std/net/http/evented"

fn http2_config() evented.Config {
  config := evented.default_config()
  config.http2 = true
  // A whole 16 KiB frame must fit the receive buffer.
  config.receive_size = 32 * mem.KiB
  config.http2_connections = 256
  config.http2_slots = 64
  return config
}
```

Memory stays fixed. An HTTP/2 connection leases one of
`Config.http2_connections` state blocks per worker (HPACK table and 100
streams, about 21 KiB). Each stream holds one of the worker's
`Config.http2_slots` request slots (`receive_size` plus `job_size`) until it
is answered; a body past its slot borrows an upload block, and a larger one
goes to `Config.on_large_body`. A stream that finds no slot is refused
(`REFUSED_STREAM`), which clients retry. A connection that finds no state
block is told to go away. With 32 KiB receive buffers the defaults (256 blocks, 64
slots) add about 7.5 MiB per worker; `evented.storage_size` counts it.

Flow control is honored both ways. A response larger than the client's
window waits inside the handler for `WINDOW_UPDATE` (up to
`write_timeout_milliseconds`), as an HTTP/1.1 response waits for the socket;
browsers grant megabytes. Pushes to an `open_stream` stream never wait: one
whose window is closed is reset. Headers are HPACK-compressed
(`std/net/http/hpack`); the server sends no dynamic-table entries, only
static indexes and Huffman-coded literals.

## HTTP/3

Experimental. HTTP/3 is off unless `Config.http3` is set, and one test
covers it, which needs OpenSSL 3.5 and a curl built with HTTP/3. Use
HTTP/2 over TLS for production; most deployments put a proxy in front for
HTTP/3 anyway.

Set `Config.http3` (with `Config.http2`) and give `Config.quic` a QUIC stack:
`https.quic(https.quic_context(arena, "cert.pem", "key.pem").value)` from
`std/net/http/evented/tls`, which uses OpenSSL's QUIC server (OpenSSL 3.5 or
later). Each worker then opens a UDP socket at the TCP listener's address
with SO_REUSEPORT, and every TCP response carries
`Alt-Svc: h3=":PORT"; ma=86400`, so browsers move to HTTP/3 on their next
request.

```dyn
use "std/mem"
use "std/net/http/evented"
use "std/net/http/evented/tls" https

fn http3_config(quic: *const evented.Quic) evented.Config {
  config := evented.default_config()
  config.receive_size = 32 * mem.KiB
  config.http2 = true
  config.http3 = true
  config.quic = quic
  return config
}
```

A QUIC connection takes a connection slot and an HTTP/2 state block, and
each request stream a request slot, so the HTTP/2 limits bound HTTP/3 too.
Streams run the same handler, with the same `run`, `open_stream`,
`receive_body` and response helpers; QUIC does flow control, and a response
that outruns it waits inside the handler as on HTTP/2. QPACK runs without a
dynamic table: the server advertises capacity 0, so header blocks decode
independently (`std/net/http/qpack`). QUIC timers (acknowledgements, loss
recovery) run in the worker's loop. Not offered over HTTP/3: server push and
WebSockets (RFC 9220); browsers keep using TCP for WebSockets.

## TLS

`std/net/http/evented/tls` supplies an OpenSSL transport for `Config.transport`;
see [tls.md](tls.md). TLS clients cannot read a 503 before their handshake,
so with `Overflow.Reject` they are closed instead.

## Not yet

- WebSockets over HTTP/3 (RFC 9220), which browsers do not use yet.
