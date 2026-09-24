# std/net

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/net-event-aarch64/main.dyn](../../tests/net-event-aarch64/main.dyn)
- [tests/net-protocol/main.dyn](../../tests/net-protocol/main.dyn)
- [tests/sdk-http-workers/main.dyn](../../tests/sdk-http-workers/main.dyn)
- [tests/stdlib-app/main.dyn](../../tests/stdlib-app/main.dyn)
- [tests/stdlib-net-event/main.dyn](../../tests/stdlib-net-event/main.dyn)
- [tests/stdlib-system/main.dyn](../../tests/stdlib-system/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/net/linux_aarch64.dyn

Target gate: `#target(arch: aarch64, kernel: linux)`

[Source](../../compiler/std/net/linux_aarch64.dyn#L3)

Linux UAPI naturally aligns the 64-bit epoll data field on AArch64.

```dyn
pub struct Event { bytes: [16]u8 }
```

## Source: compiler/std/net/linux_x86_64.dyn

Target gate: `#target(arch: x86_64, kernel: linux)`

[Source](../../compiler/std/net/linux_x86_64.dyn#L3)

Linux UAPI packs epoll_event only on x86_64.

```dyn
pub struct Event { bytes: [12]u8 }
```

## Source: compiler/std/net/net.dyn

Target gate: `#target(kernel: linux)`

[Source](../../compiler/std/net/net.dyn#L6)

```dyn
pub const AddressFamilyIpv4: usize = 2
```

[Source](../../compiler/std/net/net.dyn#L7)

```dyn
pub const AddressFamilyUnix: usize = 1
```

[Source](../../compiler/std/net/net.dyn#L8)

```dyn
pub const AddressFamilyIpv6: usize = 10
```

[Source](../../compiler/std/net/net.dyn#L9)

```dyn
pub const SocketStream: usize = 1
```

[Source](../../compiler/std/net/net.dyn#L10)

```dyn
pub const SocketDatagram: usize = 2
```

[Source](../../compiler/std/net/net.dyn#L11)

```dyn
pub const PollReadable: i16 = 1
```

[Source](../../compiler/std/net/net.dyn#L12)

```dyn
pub const PollWritable: i16 = 4
```

[Source](../../compiler/std/net/net.dyn#L13)

```dyn
pub const PollError: i16 = 8
```

[Source](../../compiler/std/net/net.dyn#L14)

```dyn
pub const PollHangup: i16 = 16
```

[Source](../../compiler/std/net/net.dyn#L15)

```dyn
pub const ShutdownRead: usize = 0
```

[Source](../../compiler/std/net/net.dyn#L16)

```dyn
pub const ShutdownWrite: usize = 1
```

[Source](../../compiler/std/net/net.dyn#L17)

```dyn
pub const ShutdownBoth: usize = 2
```

[Source](../../compiler/std/net/net.dyn#L19)

```dyn
pub struct Ipv4Address { bytes: [16]u8 }
```

[Source](../../compiler/std/net/net.dyn#L20)

```dyn
pub struct Ipv6Address { bytes: [28]u8 }
```

[Source](../../compiler/std/net/net.dyn#L21)

```dyn
pub struct UnixAddress { bytes: [110]u8, length: usize }
```

[Source](../../compiler/std/net/net.dyn#L23)

Large enough for every supported sockaddr. `length` makes ownership and ABI size explicit.

```dyn
pub struct Address { bytes: [128]u8, length: usize }
```

[Source](../../compiler/std/net/net.dyn#L24)

```dyn
pub struct PollDescriptor { descriptor: i32, events: i16, returned: i16 }
```

[Source](../../compiler/std/net/net.dyn#L26)

```dyn
pub struct Result { value: isize, error: isize, ok: bool }
```

[Source](../../compiler/std/net/net.dyn#L27)

```dyn
pub struct Connection { descriptor: isize }
```

[Source](../../compiler/std/net/net.dyn#L28)

```dyn
pub struct Listener { descriptor: isize }
```

[Source](../../compiler/std/net/net.dyn#L29)

```dyn
pub struct ConnectionResult { connection: Connection, error: isize, ok: bool }
```

[Source](../../compiler/std/net/net.dyn#L30)

```dyn
pub struct ListenerResult { listener: Listener, error: isize, ok: bool }
```

[Source](../../compiler/std/net/net.dyn#L31)

```dyn
pub fn result_value(outcome: *const Result) isize
```

[Source](../../compiler/std/net/net.dyn#L32)

```dyn
pub fn connection_result_value(outcome: *const ConnectionResult) Connection
```

[Source](../../compiler/std/net/net.dyn#L33)

```dyn
pub fn listener_result_value(outcome: *const ListenerResult) Listener
```

[Source](../../compiler/std/net/net.dyn#L40)

```dyn
pub fn socket(family: usize, kind: usize, protocol: usize) Result
```

[Source](../../compiler/std/net/net.dyn#L44)

```dyn
pub fn close(descriptor: isize) Result
```

[Source](../../compiler/std/net/net.dyn#L45)

```dyn
pub fn listen(descriptor: isize, backlog: usize) Result
```

[Source](../../compiler/std/net/net.dyn#L46)

```dyn
pub fn shutdown(descriptor: isize, how: usize) Result
```

[Source](../../compiler/std/net/net.dyn#L48)

```dyn
pub fn ipv4_address(destination: []u8, a: u8, b: u8, c: u8, d: u8, port: u16) []u8
```

[Source](../../compiler/std/net/net.dyn#L65)

```dyn
pub fn ipv4(a: u8, b: u8, c: u8, d: u8, port: u16) Ipv4Address
```

[Source](../../compiler/std/net/net.dyn#L71)

```dyn
pub fn ipv6(bytes: [16]u8, port: u16, scope: u32) Ipv6Address
```

[Source](../../compiler/std/net/net.dyn#L88)

Linux sockaddr_un. Empty result means an empty/oversized path.

```dyn
pub fn unix(path: []const u8) UnixAddress
```

[Source](../../compiler/std/net/net.dyn#L100)

```dyn
pub fn connect_ipv4(descriptor: isize, address: *const Ipv4Address) Result
```

[Source](../../compiler/std/net/net.dyn#L104)

```dyn
pub fn bind_ipv4(descriptor: isize, address: *const Ipv4Address) Result
```

[Source](../../compiler/std/net/net.dyn#L108)

```dyn
pub fn connect_ipv6(descriptor: isize, address: *const Ipv6Address) Result
```

[Source](../../compiler/std/net/net.dyn#L109)

```dyn
pub fn bind_ipv6(descriptor: isize, address: *const Ipv6Address) Result
```

[Source](../../compiler/std/net/net.dyn#L110)

```dyn
pub fn connect_unix(descriptor: isize, address: *const UnixAddress) Result
```

[Source](../../compiler/std/net/net.dyn#L114)

```dyn
pub fn bind_unix(descriptor: isize, address: *const UnixAddress) Result
```

[Source](../../compiler/std/net/net.dyn#L119)

```dyn
pub fn connect(descriptor: isize, address: []const u8) Result
```

[Source](../../compiler/std/net/net.dyn#L124)

```dyn
pub fn bind(descriptor: isize, address: []const u8) Result
```

[Source](../../compiler/std/net/net.dyn#L129)

```dyn
pub fn accept(descriptor: isize) Result
```

[Source](../../compiler/std/net/net.dyn#L131)

```dyn
pub fn tcp_listen_ipv4(address: *const Ipv4Address, backlog: usize) ListenerResult
```

[Source](../../compiler/std/net/net.dyn#L144)

```dyn
pub fn tcp_connect_ipv4(address: *const Ipv4Address) ConnectionResult
```

[Source](../../compiler/std/net/net.dyn#L153)

```dyn
pub fn listener_accept(listener: *Listener) ConnectionResult
```

[Source](../../compiler/std/net/net.dyn#L160)

```dyn
pub fn listener_close(listener: *Listener) Result
```

[Source](../../compiler/std/net/net.dyn#L167)

```dyn
pub fn connection_close(connection: *Connection) Result
```

[Source](../../compiler/std/net/net.dyn#L174)

```dyn
pub fn connection_read(connection: *Connection, destination: []u8) Result
```

[Source](../../compiler/std/net/net.dyn#L179)

```dyn
pub fn connection_write(connection: *Connection, source: []const u8) Result
```

[Source](../../compiler/std/net/net.dyn#L209)

```dyn
pub fn connection_reader(connection: *Connection) stream.Reader
```

[Source](../../compiler/std/net/net.dyn#L213)

```dyn
pub fn connection_writer(connection: *Connection) stream.Writer
```

[Source](../../compiler/std/net/net.dyn#L217)

```dyn
pub fn accept_address(descriptor: isize, address: *Address) Result
```

[Source](../../compiler/std/net/net.dyn#L224)

```dyn
pub fn local_address(descriptor: isize, address: *Address) Result
```

[Source](../../compiler/std/net/net.dyn#L231)

```dyn
pub fn peer_address(descriptor: isize, address: *Address) Result
```

[Source](../../compiler/std/net/net.dyn#L238)

```dyn
pub fn send(descriptor: isize, bytes: []const u8, flags: usize) Result
```

[Source](../../compiler/std/net/net.dyn#L245)

```dyn
pub fn receive(descriptor: isize, bytes: []u8, flags: usize) Result
```

[Source](../../compiler/std/net/net.dyn#L252)

```dyn
pub fn send_to(descriptor: isize, bytes: []const u8, flags: usize, address: []const u8) Result
```

[Source](../../compiler/std/net/net.dyn#L260)

```dyn
pub fn receive_from(descriptor: isize, bytes: []u8, flags: usize, address: []u8, address_length: *u32) Result
```

[Source](../../compiler/std/net/net.dyn#L272)

```dyn
pub fn reuse_address(descriptor: isize, enabled: bool) Result
```

[Source](../../compiler/std/net/net.dyn#L279)

Completes a nonblocking connect by reading SO_ERROR. Zero means connected.

```dyn
pub fn socket_error(descriptor: isize) Result
```

[Source](../../compiler/std/net/net.dyn#L287)

```dyn
pub fn nonblocking(descriptor: isize, enabled: bool) Result
```

[Source](../../compiler/std/net/net.dyn#L297)

```dyn
pub fn receive_timeout(descriptor: isize, milliseconds: usize) Result
```

[Source](../../compiler/std/net/net.dyn#L302)

```dyn
pub fn send_timeout(descriptor: isize, milliseconds: usize) Result
```

[Source](../../compiler/std/net/net.dyn#L307)

```dyn
pub fn would_block(outcome: *const Result) bool
```

[Source](../../compiler/std/net/net.dyn#L310)

```dyn
pub fn poll(descriptors: []PollDescriptor, timeout_milliseconds: i32) Result
```

[Source](../../compiler/std/net/net.dyn#L316)

```dyn
pub fn wait(descriptor: isize, events: i16, timeout_milliseconds: i32) Result
```

[Source](../../compiler/std/net/net.dyn#L323)

```dyn
pub fn poll_has(item: *const PollDescriptor, events: i16) bool
```

[Source](../../compiler/std/net/net.dyn#L327)

Linux epoll. Target-specific Event storage follows the kernel UAPI layout.

```dyn
pub const EventReadable: u32 = 1
```

[Source](../../compiler/std/net/net.dyn#L328)

```dyn
pub const EventWritable: u32 = 4
```

[Source](../../compiler/std/net/net.dyn#L329)

```dyn
pub const EventError: u32 = 8
```

[Source](../../compiler/std/net/net.dyn#L330)

```dyn
pub const EventHangup: u32 = 16
```

[Source](../../compiler/std/net/net.dyn#L331)

```dyn
pub const EventEdgeTriggered: u32 = 2147483648
```

[Source](../../compiler/std/net/net.dyn#L332)

```dyn
pub const EventAdd: usize = 1
```

[Source](../../compiler/std/net/net.dyn#L333)

```dyn
pub const EventRemove: usize = 2
```

[Source](../../compiler/std/net/net.dyn#L334)

```dyn
pub const EventModify: usize = 3
```

[Source](../../compiler/std/net/net.dyn#L349)

```dyn
pub fn event(events: u32, data: u64) Event
```

[Source](../../compiler/std/net/net.dyn#L356)

```dyn
pub fn event_events(value: *const Event) u32
```

[Source](../../compiler/std/net/net.dyn#L372)

```dyn
pub fn event_data(value: *const Event) u64
```

[Source](../../compiler/std/net/net.dyn#L378)

```dyn
pub fn event_queue() Result
```

[Source](../../compiler/std/net/net.dyn#L380)

```dyn
pub fn event_control(queue: isize, operation: usize, descriptor: isize, value: *Event) Result
```

[Source](../../compiler/std/net/net.dyn#L386)

Registration helpers keep epoll's operation numbers and remove-event pointer
convention out of application code. `data` is returned unchanged by event_wait.

```dyn
pub fn event_add(queue: isize, descriptor: isize, events: u32, data: u64) Result
```

[Source](../../compiler/std/net/net.dyn#L391)

```dyn
pub fn event_modify(queue: isize, descriptor: isize, events: u32, data: u64) Result
```

[Source](../../compiler/std/net/net.dyn#L396)

```dyn
pub fn event_remove(queue: isize, descriptor: isize) Result
```

[Source](../../compiler/std/net/net.dyn#L403)

```dyn
pub fn event_wait(queue: isize, events: []Event, timeout_milliseconds: i32) Result
```
