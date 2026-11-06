# Result shape: every std result, before and after

Status: applied, with the changes listed in `docs/migrations/result-shape.md`.
This document shows the shape decided on 2026-11-05 applied to every result type
in `std`. The mapping and the
signature lists are generated from the source, then reviewed by rule, not
function by function. Signatures that return a type through an import alias are
not listed, so the lists are a lower bound.

## The rule

- If the world can make a function fail, it returns `{ value, failure }`.
- If there is nothing to return, it returns the failure alone, so the discard
  rule forces a decision.
- Otherwise it returns its value.
- `Ok` is the zero variant, so an omitted failure means success.
- On failure, `value` is zero or a documented partial result. Reading it is
  always safe.
- Effects share `io.Kind` and `io.Failure`. Parsers and decoders share
  `parse.Kind` and `parse.Failure`. User code may define its own.

```dyn
// std/io
pub enum Kind { Ok, NotFound, PermissionDenied, AlreadyExists, Full, WouldBlock, Other }
pub struct Failure { kind: Kind, native: isize }
pub struct Bytes { value: []u8, failure: Failure }
pub struct Count { value: usize, failure: Failure }

// std/parse
pub enum Kind { Ok, Syntax, Truncated, Overflow, Capacity, Unsupported, Checksum, Overlap }
pub struct Failure { kind: Kind, offset: usize, message: []const u8 }
```

In the module tables below, a bare `failure` outside effect modules is a
`parse.Failure`. End of input and "try again" are not failures. They stay in
`io.Status` or a scanner's own status, so `http` `End` and `tls` `WantRead` do
not become `parse.Kind` values.

## Totals

| Outcome | Structs today |
|---|---:|
| Keep a named result with `value` and `failure` | 87 |
| Replaced by `io.Failure`, `io.Bytes` or `io.Count` | 25 |
| Become a plain value | 11 |
| Raw `os/*` layer, unchanged | 9 |
| Platform copies removed | 8 |
| Valueless parser results replaced by the module `Failure` | 2 |
| Merged into `net/dns` `Addresses` | 1 |

Of the 143 structs today, about 87 named results remain, plus `io.Failure`,
`io.Bytes`, `io.Count` and `parse.Failure`: about 91 in total. `parse.Failure`
replaces the 17 per-module `ErrorKind` enums and `CompileError`, along with
their repeated `kind`, `error`, `offset` and `detail` fields. Module-specific
detail becomes `message` text, so code can display it but not branch on it.

The earlier estimate of 30 to 60 structs was too low. It assumed handles and
decoded objects would carry their own failure, which the final design dropped.

## Extending effects and grouping failures

Std effects use `io.Kind`, which user code cannot add variants to. A user effect
defines its own `Kind` and `Failure`. Nothing is registered and no interface is
implemented.

### One new effect

```dyn
pub enum Kind { Ok, Busy, Corrupt, Disk }
pub struct Failure { kind: Kind, disk: io.Failure, page: usize }
pub struct Row { value: []const u8, failure: Failure }

pub fn read_row(store: *Store, page: usize) Row
```

### A function that can fail in several ways

Give the function one `Kind` naming which source failed, with one field per
source. Each source keeps its own type and detail. The example below was
compiled and run with stand-in `io` and `png` types.

```dyn
pub enum Kind { Ok, Disk, Image, TooLarge }
pub struct Failure { kind: Kind, disk: io.Failure, image: png.Failure, limit: usize }
pub struct Loaded { value: png.Image, failure: Failure }

fn load(arena: *mem.Arena, path: []const u8) Loaded {
  read := fs.read_file(arena, path)
  if read.failure.kind != io.Kind.Ok {
    return Loaded{ failure: Failure{ kind: Kind.Disk, disk: read.failure } }
  }
  decoded := png.decode(arena, read.value)
  if decoded.failure.kind != png.Kind.Ok {
    return Loaded{ value: decoded.value, failure: Failure{ kind: Kind.Image, image: decoded.failure } }
  }
  return Loaded{ value: decoded.value }
}
```

The caller branches on the group, then reads the detail it wants.

```dyn
loaded := load(arena, path)
show(loaded.value)
if loaded.failure.kind == Kind.Disk {
  report_disk(loaded.failure.disk)
}
if loaded.failure.kind == Kind.Image {
  report_image(loaded.failure.image.offset)
}
```

Only the field named by `kind` is meaningful. The others stay zero. A `union`
would save space but cannot be read safely without checking `kind`, so prefer
plain fields unless the failure is stored in bulk.

### Grouping by meaning instead of source

When callers do not care which layer failed, translate into their terms. Use a
table indexed by the dense source enum.

```dyn
pub enum Kind { Ok, Missing, Denied, Failed }

fn from_io(kind: io.Kind) Kind {
  table: [7]Kind = [Kind.Ok, Kind.Missing, Kind.Denied, Kind.Failed, Kind.Failed, Kind.Failed, Kind.Failed]
  return table[#cast(usize, kind)]
}
```

### Collecting many failures

A batch keeps going and returns every failure as data.

```dyn
pub struct Batch { loaded: []png.Image, failures: []Failure }
```

### Forwarding

Forward without wrapping when the types match.

```dyn
return Bytes{ failure: opened.failure }
```

A failure type is only worth defining when a caller branches on it or displays
it. Otherwise forward the source failure unchanged.

## Every module

### `std/archive/tar`

| Today | Becomes |
|---|---|
| `Result` | `Result { value: Entry, status, failure }` |

```dyn
fn next(state: *ArchiveReader) Result
fn read_stream(state: *StreamReader, destination: []u8) Result
```

### `std/archive/zip`

| Today | Becomes |
|---|---|
| `OpenResult` | `OpenResult { value: ArchiveReader, failure }` |
| `EntryResult` | `EntryResult { value: Entry, failure }` |
| `ExtractResult` | `ExtractResult { value: []u8, failure }` |

```dyn
fn extract(arena: *mem.Arena, archive_entry: Entry) ExtractResult
fn next(state: *ArchiveReader) EntryResult
fn next_stream(state: *StreamReader) EntryResult
fn open_checked(source: []const u8) OpenResult
```

### `std/audio/wav`

| Today | Becomes |
|---|---|
| `DecodeResult` | `DecodeResult { value: Audio, failure }` |
| `EncodeResult` | `EncodeResult { value: []u8, failure }` |

```dyn
fn decode(arena: *mem.Arena, source: []const u8) DecodeResult
fn encode(arena: *mem.Arena, audio: *const Audio, encoding: Encoding) EncodeResult
```

### `std/c`

| Today | Becomes |
|---|---|
| `BytesResult` | `BytesResult { value: []const u8, failure }` |

```dyn
fn bytes_from_string(value: string, maximum: usize) BytesResult
```

### `std/compress/deflate`

| Today | Becomes |
|---|---|
| `Result` | `Transfer { written, consumed, failure }` |

```dyn
fn deflate_dynamic_chunk(destination: []u8, input: []const u8, final: bool, scratch: []usize) Transfer
fn deflate_fixed_chunk(destination: []u8, input: []const u8, final: bool, scratch: []usize) Transfer
fn deflate_stored_chunk(destination: []u8, input: []const u8, final: bool) Transfer
fn resume(state: *InflateState, destination: []u8, input: []const u8) Transfer
fn resume_gzip(state: *GzipState, destination: []u8, input: []const u8) Transfer
```

### `std/compress/zstd`

| Today | Becomes |
|---|---|
| `BufferResult` | `BufferResult { value: []u8, failure }` |
| `SizeResult` | `SizeResult { value: u64, failure } (zero value means unknown size)` |

```dyn
fn compress(arena: *memory.Arena, source: []const u8, level: i32) BufferResult
fn decompress(arena: *memory.Arena, source: []const u8) BufferResult
fn frame_size(source: []const u8) SizeResult
```

### `std/crypto/aead`

| Today | Becomes |
|---|---|
| `OpenResult` | `OpenResult { value: []u8, failure }` |
| `SealResult` | `SealResult { value: Sealed, failure }` |

```dyn
fn open(arena: *mem.Arena, kind: Cipher, ciphertext: []const u8, tag: []const u8, additional: []const u8, key: []const u8, nonce: []const u8) OpenResult
fn seal(arena: *mem.Arena, kind: Cipher, plaintext: []const u8, additional: []const u8, key: []const u8, nonce: []const u8) SealResult
```

### `std/crypto/certificate`

| Today | Becomes |
|---|---|
| `Result` | `Result { value: Certificate, failure }` |

```dyn
fn parse(encoded: []const u8) Result
```

### `std/crypto/der`

| Today | Becomes |
|---|---|
| `Result` | `Result { value: Element, failure }` |

```dyn
fn next(state: *Cursor) Result
```

### `std/crypto/pem`

| Today | Becomes |
|---|---|
| `Result` | `Block { value, label, consumed, failure }` |

```dyn
fn decode(arena: *mem.Arena, source: []const u8) Block
```

### `std/crypto/x509`

| Today | Becomes |
|---|---|
| `InspectResult` | `InspectResult { value, failure } (Reason becomes message text)` |

```dyn
fn inspect(encoded: []const u8) InspectResult
```

### `std/dynlib`

| Today | Becomes |
|---|---|
| `OpenResult` | `OpenResult { value: Handle, failure: io.Failure }` |
| `Result` | `io.Failure` |
| `SymbolResult` | `SymbolResult { value: rawptr, failure: io.Failure }` |

```dyn
fn close(handle: *Handle) io.Failure
fn open(path: []const u8, flags: i32) OpenResult
fn symbol(handle: Handle, name: []const u8) SymbolResult
```

### `std/embedded/timer`

| Today | Becomes |
|---|---|
| `Result` | `io.Failure` |

```dyn
fn start(timer: *const SysTick, period: u32, interrupt: bool, processor_clock: bool) io.Failure
```

### `std/encoding`

| Today | Becomes |
|---|---|
| `Result` | `Result { value: []u8, required, failure }` |

### `std/encoding/cbor`

| Today | Becomes |
|---|---|
| `EncodeResult` | `EncodeResult { value: []u8, failure }` |
| `Result` | `Result { value: Token, failure }` |

```dyn
fn encode(arena: *mem.Arena, tokens: []const Token) EncodeResult
fn next(state: *Reader) Result
```

### `std/encoding/ini`

| Today | Becomes |
|---|---|
| `Result` | Entry, zero when no result |

```dyn
fn next(state: *Scanner) Entry
```

### `std/encoding/json`

| Today | Becomes |
|---|---|
| `ParseResult` | `ParseResult { value: *const Value, failure }` |

```dyn
fn parse(arena: *memory.Arena, source: []const u8) ParseResult
```

### `std/encoding/json/read`

| Today | Becomes |
|---|---|
| `ParseResult` | `ParseResult { value: *const Value, failure }` |

```dyn
fn parse(arena: *memory.Arena, source: []const u8) ParseResult
```

### `std/encoding/mdesk`

| Today | Becomes |
|---|---|
| `ParseResult` | `ParseResult { value: *Node, failure }` |

```dyn
fn parse(arena: *mem.Arena, source: []const u8) ParseResult
```

### `std/encoding/msgpack`

| Today | Becomes |
|---|---|
| `EncodeResult` | `EncodeResult { value: []u8, failure }` |
| `Result` | `Result { value: Token, failure }` |

```dyn
fn encode(arena: *mem.Arena, tokens: []const Token) EncodeResult
fn next(state: *Reader) Result
```

### `std/encoding/protobuf`

| Today | Becomes |
|---|---|
| `EncodeResult` | `EncodeResult { value: []u8, failure }` |
| `FieldResult` | `FieldResult { value: Field, failure }` |

```dyn
fn encode(arena: *mem.Arena, fields: []const Field) EncodeResult
fn next(state: *Reader) FieldResult
```

### `std/encoding/toml`

| Today | Becomes |
|---|---|
| `EncodeResult` | `EncodeResult { value: []u8, failure }` |
| `ParseResult` | `ParseResult { value: *const Value, failure }` |

```dyn
fn encode(arena: *mem.Arena, root: *const Value) EncodeResult
fn parse(arena: *mem.Arena, source: []const u8) ParseResult
```

### `std/encoding/xml`

| Today | Becomes |
|---|---|
| `ParseResult` | `ParseResult { value: *const Node, failure }` |
| `Result` | `Result { value: Event, failure }` |

```dyn
fn next(state: *Scanner) Result
fn next_stream(state: *StreamScanner) Result
fn parse(arena: *tree_memory.Arena, source: []const u8) ParseResult
```

### `std/event`

| Today | Becomes |
|---|---|
| `OpenResult` | `OpenResult { value: Queue, failure: io.Failure }` |
| `Result` | `io.Failure` |
| `WaitResult` | `WaitResult { value: []Event, failure: io.Failure }` |

```dyn
fn add(queue: *Queue, descriptor: isize, events: u32, token: u64) io.Failure
fn close(queue: *Queue) io.Failure
fn modify(queue: *Queue, descriptor: isize, events: u32, token: u64) io.Failure
fn open(arena: *mem.Arena, capacity: usize) OpenResult
fn remove(queue: *Queue, descriptor: isize) io.Failure
fn wait(arena: *mem.Arena, queue: *Queue, timeout_milliseconds: i32) WaitResult
```

### `std/flags`

| Today | Becomes |
|---|---|
| `Result` | `Result { value: Parsed, failure } (option name moves into message text)` |
| `TextResult` | `TextResult { value: []u8, required, failure }` |

```dyn
fn parse(arena: *memory.Arena, options: []const Option, arguments: [][]const u8) Result
```

### `std/font`

| Today | Becomes |
|---|---|
| `AtlasResult` | `AtlasResult { value: Atlas, failure }` |
| `BitmapResult` | `BitmapResult { value: Bitmap, failure }` |
| `FaceResult` | `FaceResult { value: Face, failure }` |

```dyn
fn atlas(arena: *mem.Arena, face: *const Face, codepoints: []const u32, pixels_per_em: u16, width, height: i32) AtlasResult
fn open(data: []const u8) FaceResult
fn raster(arena: *mem.Arena, face: *const Face, index: u16, pixels_per_em: u16) BitmapResult
```

### `std/fs`

| Today | Becomes |
|---|---|
| `FileResult` | `FileResult { value: File, failure: io.Failure }` |
| `Mapping` | `io.Bytes` |
| `OffsetResult` | `io.Count` |
| `ReadAllResult` | `io.Bytes` |
| `Result` | `io.Count` |
| `AtomicResult` | `AtomicResult { value: AtomicFile, failure: io.Failure }` |
| `DirectoryResult` | `DirectoryResult { value: Directory, failure: io.Failure }` |
| `PathResult` | `io.Bytes` |

```dyn
fn app_directory(arena: *mem.Arena, kind: AppDirectory) io.Bytes
fn append(path: []const u8) FileResult
fn atomic_abort(transaction: *AtomicFile) io.Count
fn atomic_begin(destination: []const u8, temporary: []const u8) AtomicResult
fn atomic_commit(transaction: *AtomicFile) io.Count
fn atomic_commit_durable(transaction: *AtomicFile, parent_directory: []const u8) io.Count
fn close(file: *File) io.Count
fn close_directory(directory: *Directory) io.Count
fn copy_file(source: []const u8, destination: []const u8, scratch: []u8) io.Count
fn create(path: []const u8) FileResult
fn create_exclusive(path: []const u8) FileResult
fn lock(file: *File, operation: usize) io.Count
fn make_directory(path: []const u8, mode: usize) io.Count
fn map(file: *const File) io.Bytes
fn open(path: []const u8) FileResult
fn read(file: *File, destination: []u8) io.Count
fn read_all(arena: *memory.Arena, path: []const u8, maximum: usize) io.Bytes
fn read_link(arena: *mem.Arena, path: []const u8) io.Bytes
fn remove(path: []const u8) io.Count
fn remove_directory(path: []const u8) io.Count
fn remove_tree(path: []const u8, frames: []RemovalFrame, scratch: []u8) io.Count
fn rename(old_path: []const u8, new_path: []const u8) io.Count
fn seek(file: *File, offset: isize, origin: usize) io.Count
fn symbolic_link(target: []const u8, link: []const u8) io.Count
fn sync(file: *File) io.Count
fn sync_directory(path: []const u8) io.Count
fn truncate(path: []const u8, length: usize) io.Count
fn unmap(mapping: *Mapping) io.Count
fn write(file: *File, source: []const u8) io.Count
fn write_all(path: []const u8, source: []const u8) io.Count
fn write_atomic(destination: []const u8, temporary: []const u8, source: []const u8) io.Count
```

### `std/fs/capability`

| Today | Becomes |
|---|---|
| `ReadResult` | `io.Count` |

```dyn
fn read(directory: *const Directory, path: []const u8, destination: []u8) io.Count
```

### `std/fs/watch`

| Today | Becomes |
|---|---|
| `EventResult` | platform copy of the shared definition |
| `OpenResult` | platform copy of the shared definition |
| `Result` | platform copy of the shared definition |

### `std/image/bmp`

| Today | Becomes |
|---|---|
| `EncodeResult` | `EncodeResult { value: []u8, failure }` |
| `Result` | `Result { value: Image, failure }` |

```dyn
fn decode(arena: *mem.Arena, source: []const u8) Result
fn encode(arena: *mem.Arena, pixels: []const u8, width, height: u32, channels: u8) EncodeResult
```

### `std/image/gif`

| Today | Becomes |
|---|---|
| `Result` | `Result { value: Image, consumed, failure }` |

```dyn
fn decode(arena: *mem.Arena, source: []const u8) Result
```

### `std/image/jpeg`

| Today | Becomes |
|---|---|
| `Result` | `Result { value: Image, failure }` |

```dyn
fn decode(arena: *mem.Arena, source: []const u8) Result
```

### `std/image/png`

| Today | Becomes |
|---|---|
| `EncodeResult` | `EncodeResult { value: []u8, failure }` |
| `InfoResult` | `InfoResult { value: Info, failure }` |
| `Result` | `Result { value: Image, failure }` |

```dyn
fn decode(arena: *mem.Arena, source: []const u8) Result
fn encode(arena: *mem.Arena, pixels: []const u8, width: u32, height: u32, channels: u8) EncodeResult
fn inspect(source: []const u8) InfoResult
```

### `std/image/pnm`

| Today | Becomes |
|---|---|
| `EncodeResult` | `EncodeResult { value: []u8, failure }` |
| `Result` | `Result { value: Image, consumed, failure }` |

```dyn
fn decode(arena: *mem.Arena, source: []const u8) Result
fn encode(arena: *mem.Arena, pixels: []const u8, width: u32, height: u32, channels: u8) EncodeResult
```

### `std/image/qoi`

| Today | Becomes |
|---|---|
| `EncodeResult` | `EncodeResult { value: []u8, failure }` |
| `InfoResult` | `InfoResult { value: Info, failure }` |
| `Result` | `Result { value: Image, failure }` |

```dyn
fn decode(arena: *mem.Arena, source: []const u8) Result
fn encode(arena: *mem.Arena, pixels: []const u8, width: u32, height: u32, channels: u8, srgb: bool) EncodeResult
fn inspect(source: []const u8) InfoResult
```

### `std/image/tga`

| Today | Becomes |
|---|---|
| `EncodeResult` | `EncodeResult { value: []u8, failure }` |
| `Result` | `Result { value: Image, failure }` |

```dyn
fn decode(arena: *mem.Arena, source: []const u8) Result
fn encode(arena: *mem.Arena, pixels: []const u8, width, height: u32, channels: u8) EncodeResult
```

### `std/math`

| Today | Becomes |
|---|---|
| `Mat3Result` | Mat3, zero when no result |
| `Mat4Result` | Mat4, zero when no result |
| `QuatResult` | Quat, zero when no result |
| `RotationVectorResult` | Vec3, zero when no result |

```dyn
fn mat3_inverse(a: Mat3) Mat3
fn mat3_rotate(angle: f32) Mat3
fn mat3_scale(v: Vec2) Mat3
fn mat3_translate(v: Vec2) Mat3
fn mat4_inverse(a: Mat4) Mat4
fn mat4_look_at(eye, target, up: Vec3) Mat4
fn mat4_orthographic(left, right, bottom, top, near, far: f32) Mat4
fn mat4_perspective(fov_y, aspect, near, far: f32) Mat4
fn mat4_rotate(axis: Vec3, angle: f32) Mat4
fn mat4_scale(v: Vec3) Mat4
fn mat4_translate(v: Vec3) Mat4
fn quat_from_rotation_vector(v: Vec3) Quat
fn quat_normalize(q: Quat) Quat
fn quat_to_mat3(q: Quat) Mat3
fn quat_to_rotation_vector(q: Quat) Vec3
```

### `std/math/big`

| Today | Becomes |
|---|---|
| `ModResult` | Int, zero when no result |
| `ParseResult` | `ParseResult { value: Int, failure }` |
| `U64Result` | `U64Result { value, failure }` |

```dyn
fn parse(arena: *mem.Arena, text: []const u8, base: u32) ParseResult
fn power_mod(arena: *mem.Arena, base: Int, exponent: Int, modulus: Int) Int
fn to_u64(value: Int) U64Result
```

### `std/mem`

| Today | Becomes |
|---|---|
| `SizeResult` | `SizeResult { value, failure }` |

```dyn
fn size_for(count: usize, element_size: usize) SizeResult
```

### `std/net`

| Today | Becomes |
|---|---|
| `ConnectionResult` | `ConnectionResult { value: Connection, failure: io.Failure }` |
| `ListenerResult` | `ListenerResult { value: Listener, failure: io.Failure }` |
| `Result` | `io.Count` |

```dyn
fn accept(descriptor: isize) io.Count
fn accept_address(descriptor: isize, address: *Address) io.Count
fn bind(descriptor: isize, address: []const u8) io.Count
fn bind_ipv4(descriptor: isize, address: *const Ipv4Address) io.Count
fn bind_ipv6(descriptor: isize, address: *const Ipv6Address) io.Count
fn bind_unix(descriptor: isize, address: *const UnixAddress) io.Count
fn close(descriptor: isize) io.Count
fn connect(descriptor: isize, address: []const u8) io.Count
fn connect_ipv4(descriptor: isize, address: *const Ipv4Address) io.Count
fn connect_ipv6(descriptor: isize, address: *const Ipv6Address) io.Count
fn connect_unix(descriptor: isize, address: *const UnixAddress) io.Count
fn connection_close(connection: *Connection) io.Count
fn connection_read(connection: *Connection, destination: []u8) io.Count
fn connection_write(connection: *Connection, source: []const u8) io.Count
fn event_add(queue: isize, descriptor: isize, events: u32, data: u64) io.Count
fn event_control(queue: isize, operation: usize, descriptor: isize, value: *Event) io.Count
fn event_modify(queue: isize, descriptor: isize, events: u32, data: u64) io.Count
fn event_queue() io.Count
fn event_remove(queue: isize, descriptor: isize) io.Count
fn event_wait(queue: isize, events: []Event, timeout_milliseconds: i32) io.Count
fn listen(descriptor: isize, backlog: usize) io.Count
fn listener_accept(listener: *Listener) ConnectionResult
fn listener_close(listener: *Listener) io.Count
fn local_address(descriptor: isize, address: *Address) io.Count
fn multicast_interface_ipv4(descriptor: isize, interface: [4]u8) io.Count
fn multicast_join_ipv4(descriptor: isize, group: [4]u8, interface: [4]u8) io.Count
fn multicast_leave_ipv4(descriptor: isize, group: [4]u8, interface: [4]u8) io.Count
fn multicast_loop_ipv4(descriptor: isize, enabled: bool) io.Count
fn multicast_ttl_ipv4(descriptor: isize, ttl: u8) io.Count
fn nonblocking(descriptor: isize, enabled: bool) io.Count
fn peer_address(descriptor: isize, address: *Address) io.Count
fn poll(descriptors: []PollDescriptor, timeout_milliseconds: i32) io.Count
fn receive(descriptor: isize, bytes: []u8, flags: usize) io.Count
fn receive_from(descriptor: isize, bytes: []u8, flags: usize, address: []u8, address_length: *u32) io.Count
fn receive_packet(descriptor: isize, bytes: []u8) io.Count
fn receive_timeout(descriptor: isize, milliseconds: usize) io.Count
fn reuse_address(descriptor: isize, enabled: bool) io.Count
fn send(descriptor: isize, bytes: []const u8, flags: usize) io.Count
fn send_timeout(descriptor: isize, milliseconds: usize) io.Count
fn send_to(descriptor: isize, bytes: []const u8, flags: usize, address: []const u8) io.Count
fn shutdown(descriptor: isize, how: usize) io.Count
fn socket(family: usize, kind: usize, protocol: usize) io.Count
fn socket_error(descriptor: isize) io.Count
fn tcp_connect_ipv4(address: *const Ipv4Address) ConnectionResult
fn tcp_connect_ipv6(address: *const Ipv6Address) ConnectionResult
fn tcp_listen_ipv4(address: *const Ipv4Address, backlog: usize) ListenerResult
fn tcp_listen_ipv6(address: *const Ipv6Address, backlog: usize) ListenerResult
fn unix_connect(address: *const UnixAddress) ConnectionResult
fn unix_listen(address: *const UnixAddress, backlog: usize) ListenerResult
fn wait(descriptor: isize, events: i16, timeout_milliseconds: i32) io.Count
```

### `std/net/dns`

| Today | Becomes |
|---|---|
| `Ipv4Result` | `Addresses { ipv4, ipv6, failure: io.Failure }` |
| `Ipv6Result` | `Addresses { ipv4, ipv6, failure: io.Failure }` |

```dyn
fn parse_ipv4(arena: *mem.Arena, packet: []const u8, identifier: u16, name: []const u8) Addresses
fn parse_ipv6(arena: *mem.Arena, packet: []const u8, identifier: u16, name: []const u8) Addresses
fn resolve_ipv4(arena: *mem.Arena, name: []const u8, server: *const network.Ipv4Address, timeout_milliseconds: i32) Addresses
fn resolve_ipv6(arena: *mem.Arena, name: []const u8, server: *const network.Ipv4Address, timeout_milliseconds: i32) Addresses
```

### `std/net/http`

| Today | Becomes |
|---|---|
| `AcceptResult` | `AcceptResult { value: Connection, failure: io.Failure }` |

```dyn
fn accept(listener: *Listener) AcceptResult
```

### `std/net/http/concurrent`

| Today | Becomes |
|---|---|
| `Result` | `io.Count` |

```dyn
fn join(workers: []Worker) io.Count
fn start(arena: *mem.Arena, workers: []Worker, listener: *http.Listener, receive_storage: []u8, worker_storage_size: usize, stacks: []u8, stack_size: usize, handler: http.Handler) io.Count
fn start_context(arena: *mem.Arena, workers: []Worker, listener: *http.Listener, receive_storage: []u8, worker_storage_size: usize, stacks: []u8, stack_size: usize, handler: http.Handler, context: rawptr) io.Count
```

### `std/net/tls`

| Today | Becomes |
|---|---|
| `ConnectionResult` | `ConnectionResult { value: Connection, failure: io.Failure }` |
| `ContextResult` | `ContextResult { value: Context, failure: io.Failure }` |
| `Result` | `io.Count (provider code moves to Connection)` |
| `TextResult` | `io.Bytes` |

```dyn
fn certificate_subject(arena: *memory.Arena, certificate: Certificate) io.Bytes
fn client_config_create() ContextResult
fn client_connection_create(arena: *memory.Arena, context: Context, descriptor: i32, hostname: []const u8,) ConnectionResult
fn handshake(connection: Connection) io.Count
fn read(connection: Connection, destination: []u8) io.Count
fn server_config_create(arena: *memory.Arena, certificate: []const u8, key: []const u8,) ContextResult
fn server_connection_create(context: Context, descriptor: i32) ConnectionResult
fn server_handshake(connection: Connection) io.Count
fn set_alpn_protocols(connection: Connection, protocols: []const u8) io.Count
fn shutdown(connection: Connection) io.Count
fn write(connection: Connection, source: []const u8) io.Count
```

### `std/net/url`

| Today | Becomes |
|---|---|
| `EncodingResult` | `io.Bytes` |
| `ParseResult` | `ParseResult { value: URL, failure: io.Failure }` |

```dyn
fn parse(text: []const u8) ParseResult
fn percent_decode(arena: *mem.Arena, source: []const u8) io.Bytes
```

### `std/net/websocket`

| Today | Becomes |
|---|---|
| `Result` | `io.Failure` |

```dyn
fn connection_close(state: *WebSocketConnection, payload: []const u8, mask: u32) io.Failure
fn connection_ping(state: *WebSocketConnection, payload: []const u8, mask: u32) io.Failure
fn connection_pong(state: *WebSocketConnection, payload: []const u8, mask: u32) io.Failure
fn connection_send(state: *WebSocketConnection, opcode: u8, payload: []const u8, final: bool, mask: u32) io.Failure
fn validate_upgrade_response(response: []const u8, key: []const u8) io.Failure
```

### `std/os/linux`

| Today | Becomes |
|---|---|
| `EnvironmentResult` | unchanged thin layer |
| `PathResult` | unchanged thin layer |
| `PipeResult` | unchanged thin layer |
| `Result` | unchanged thin layer |
| `SpawnResult` | unchanged thin layer |
| `WaitResult` | unchanged thin layer |

### `std/os/macos`

| Today | Becomes |
|---|---|
| `IoResult` | unchanged thin layer |

### `std/os/wasi`

| Today | Becomes |
|---|---|
| `OpenResult` | unchanged thin layer |

### `std/os/windows`

| Today | Becomes |
|---|---|
| `IoResult` | unchanged thin layer |

### `std/path`

| Today | Becomes |
|---|---|
| `Result` | `Result { value: []u8, failure }` |

```dyn
fn clean(arena: *mem.Arena, path: []const u8) Result
fn join(arena: *mem.Arena, left: []const u8, right: []const u8) Result
fn relative(arena: *mem.Arena, base: []const u8, target: []const u8) Result
fn safe_join(arena: *mem.Arena, root: []const u8, child: []const u8) Result
```

### `std/process`

| Today | Becomes |
|---|---|
| `ArgumentsResult` | `io.Bytes` |
| `CaptureResult` | `Capture { output, errors, exit, timed_out, limit_reached, failure: io.Failure }` |
| `EnvironmentResult` | []u8, empty when unset |
| `ExitResult` | `Exit { code, signal, finished, failure: io.Failure }` |
| `Pipe` | `Pipe { input, output, failure: io.Failure }` |
| `SpawnResult` | `SpawnResult { value: Child, failure: io.Failure }` |
| `Status` | `io.Failure` |

```dyn
fn arguments(arena: *mem.Arena) io.Bytes
fn capture(arena: *mem.Arena, path: []const u8, arguments: [][]const u8, configuration: Options, policy: CaptureOptions) Capture
fn close_pipe(handle: isize) io.Failure
fn environment(arena: *mem.Arena, name: []const u8) []u8
fn pipe() Pipe
fn spawn(arena: *mem.Arena, path: []const u8, arguments: [][]const u8, configuration: Options) SpawnResult
fn terminate(child: *Child) io.Failure
fn wait(child: *Child, nonblocking: bool) Exit
```

### `std/process/signal`

| Today | Becomes |
|---|---|
| `Result` | `io.Failure` |
| `WatchResult` | `WatchResult { value: Watch, failure: io.Failure }` |

```dyn
fn close(state: *Watch) io.Failure
fn watch(set: Set) WatchResult
```

### `std/profile`

| Today | Becomes |
|---|---|
| `Result` | `io.Failure` |

```dyn
fn finish(destination: *Trace, span: Span) io.Failure
```

### `std/semver`

| Today | Becomes |
|---|---|
| `ParseResult` | `ParseResult { value: Version, failure }` |

```dyn
fn parse(text: []const u8) ParseResult
```

### `std/sync`

| Today | Becomes |
|---|---|
| `ConditionWaitResult` | `ConditionWaitResult { value: bool, failure: io.Failure } (value true means signaled)` |

```dyn
fn condition_wait_timeout(value: *Condition, lock_value: *Mutex, timeout: i64) ConditionWaitResult
```

### `std/terminal`

| Today | Becomes |
|---|---|
| `Result` | `io.Failure` |

```dyn
fn restore(descriptor: isize, saved: *const State) io.Failure
```

### `std/testing`

| Today | Becomes |
|---|---|
| `TemporaryResult` | `TemporaryResult { value: TemporaryDirectory, failure: io.Failure }` |

```dyn
fn temporary_directory(arena: *mem.Arena, prefix: []const u8) TemporaryResult
```

### `std/text/edit`

| Today | Becomes |
|---|---|
| `ContextResult` | `ContextResult { value: Context, failure }` |
| `Status` | `parse.Failure` |

```dyn
fn apply(scratch: *mem.Arena, buffer: *Buffer, replacement: *const Replacement) Failure
fn snapshot(tracker: *Tracker, owner: u64, text: []const u8, cursor, anchor: usize, cause: Cause) ContextResult
fn validate(context: *const Context) Failure
```

### `std/text/layout`

| Today | Becomes |
|---|---|
| `Result` | `Result { value: Layout, failure }` |

```dyn
fn build(arena: *mem.Arena, source: []const u8, font: Font, requested: Options) Result
```

### `std/text/regex`

| Today | Becomes |
|---|---|
| `MatchResult` | `MatchResult { value: Match, captures, failure }` |
| `Result` | `Result { value: Program, failure }` |

```dyn
fn compile(arena: *mem.Arena, pattern: []const u8) Result
fn find(program: Program, text: []const u8) MatchResult
fn next(state: *Iterator) MatchResult
```

### `std/text/template`

| Today | Becomes |
|---|---|
| `ParseResult` | `ParseResult { value: Template, failure }` |
| `RenderResult` | `parse.Failure` |

```dyn
fn parse(arena: *memory.Arena, source: []const u8) ParseResult
fn render(destination: stream.Writer, template: *const Template, fields: []const Field) Failure
fn render_with(destination: stream.Writer, template: *const Template, fields: []const Field, render_field: fn(stream.Writer, []const u8) RenderResult) Failure
```

### `std/thread`

| Today | Becomes |
|---|---|
| `Result` | `io.Count` |
| `SpawnResult` | `SpawnResult { value: *Thread, failure: io.Failure }` |

```dyn
fn join(thread: *Thread) io.Count
fn spawn(arena: *mem.Arena, stack: []u8, entry: fn(rawptr) isize, context: rawptr) SpawnResult
fn spawn_with_size(arena: *mem.Arena, size: usize, entry: fn(rawptr) isize, context: rawptr) SpawnResult
fn spawn_with_size(arena: *mem.Arena, stack_size: usize, entry: fn(rawptr) isize, context: rawptr) SpawnResult
fn yield_now() io.Count
```

### `std/thread/pool`

| Today | Becomes |
|---|---|
| `Result` | `io.Failure` |
| `StartResult` | `StartResult { value: *Pool, failure: io.Failure }` |

```dyn
fn start(arena: *mem.Arena, workers: usize, capacity: usize, stack_size: usize) StartResult
fn stop(pool: *Pool) io.Failure
```

### `std/time`

| Today | Becomes |
|---|---|
| `ClockResult` | Instant |
| `DeadlineResult` | `DeadlineResult { value: Deadline, failure: io.Failure }` |
| `DurationResult` | i64 |
| `ExpiredResult` | bool |
| `SleepResult` | `io.Failure` |

```dyn
fn checked_add(a, b: i64) i64
fn checked_sub(a, b: i64) i64
fn deadline_after(duration: i64) DeadlineResult
fn deadline_expired(deadline: *const Deadline) bool
fn deadline_remaining(deadline: *const Deadline) i64
fn elapsed(start, end: Instant) i64
fn monotonic_now() Instant
fn realtime_now() Instant
fn sleep(duration: i64) io.Failure
```

### `std/time/zone`

| Today | Becomes |
|---|---|
| `ZoneResult` | `ZoneResult { value: Zone, failure: io.Failure }` |

```dyn
fn load(arena: *mem.Arena, name: []const u8) ZoneResult
fn parse_posix(arena: *mem.Arena, text: []const u8) ZoneResult
fn parse_tzif(arena: *mem.Arena, name: []const u8, data: []const u8) ZoneResult
fn system(arena: *mem.Arena) ZoneResult
```

### `std/ui/box`

| Today | Becomes |
|---|---|
| `StateResult` | *State, zero when no result |

### `std/ui/software`

| Today | Becomes |
|---|---|
| `Result` | `io.Failure` |

```dyn
fn render(surface: *Surface, commands: *const ui.Command, font: Font) io.Failure
```

### `std/unicode/text`

| Today | Becomes |
|---|---|
| `GraphemeResult` | `GraphemeResult { value: []const u8, failure }` |

```dyn
fn next_grapheme(state: *Graphemes) GraphemeResult
```
