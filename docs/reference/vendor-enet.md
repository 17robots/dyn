# vendor/enet

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: [projects/enet-example/main.dyn](../../projects/enet-example/main.dyn), [tests/vendor-extra.py](../../tests/vendor-extra.py)

## Declarations and source contracts

## Source: compiler/vendor/enet/enet.dyn

[Source](../../compiler/vendor/enet/enet.dyn#L6)

ENet 1.3.18, configurable reliable channels. Provider owns hosts/packets. Initialize once
before creating hosts and deinitialize after destroying all hosts. Hosts and
their borrowed peer handles are single-threaded. This is not encrypted transport.

```dyn
pub type Host = rawptr
```

[Source](../../compiler/vendor/enet/enet.dyn#L7)

```dyn
pub type Peer = rawptr
```

[Source](../../compiler/vendor/enet/enet.dyn#L8)

```dyn
pub type Packet = rawptr
```

[Source](../../compiler/vendor/enet/enet.dyn#L9)

```dyn
pub const Connected: i32 = 1
```

[Source](../../compiler/vendor/enet/enet.dyn#L10)

```dyn
pub const Disconnected: i32 = 2
```

[Source](../../compiler/vendor/enet/enet.dyn#L11)

```dyn
pub const Received: i32 = 3
```

[Source](../../compiler/vendor/enet/enet.dyn#L12)

```dyn
pub struct Event { kind: i32, peer: Peer, packet: Packet, code: i32, ok: bool, channel: u8, data: u32 }
```

[Source](../../compiler/vendor/enet/enet.dyn#L13)

```dyn
pub fn init() bool
```

[Source](../../compiler/vendor/enet/enet.dyn#L14)

```dyn
pub extern fn quit "enet_deinitialize"()
```

[Source](../../compiler/vendor/enet/enet.dyn#L16)

Convenience listener uses loopback and one channel; port=0 is ephemeral.

```dyn
pub fn listen_owned(port: u16, peers: usize) Host
```

[Source](../../compiler/vendor/enet/enet.dyn#L17)

```dyn
pub fn client_owned(peers: usize) Host
```

[Source](../../compiler/vendor/enet/enet.dyn#L18)

```dyn
pub fn destroy_owned(host: Host)
```

[Source](../../compiler/vendor/enet/enet.dyn#L19)

```dyn
pub extern fn port "dyn_enet_port"(host: Host) u16
```

[Source](../../compiler/vendor/enet/enet.dyn#L20)

```dyn
pub fn connect(host: Host, ip: []const u8, port: u16, buffer: []u8) Peer
```

[Source](../../compiler/vendor/enet/enet.dyn#L25)

Service both endpoints. code=0 means no event; positive means an event.
Every received packet must be destroyed, including packets the app ignores.

```dyn
pub fn service(host: Host, timeout_ms: u32) Event
```

[Source](../../compiler/vendor/enet/enet.dyn#L30)

Copies bytes; successful send transfers the private packet to ENet. Maximum 1 MiB.

```dyn
pub fn send(peer: Peer, bytes: []const u8) bool
```

[Source](../../compiler/vendor/enet/enet.dyn#L31)

```dyn
pub fn send_channel(peer: Peer, channel: u8, bytes: []const u8) bool
```

[Source](../../compiler/vendor/enet/enet.dyn#L37)

Borrow expires at packet_destroy. Received packet can be copied into an arena
if it needs to survive event handling.

```dyn
pub fn packet_bytes(packet: Packet) []const u8
```

[Source](../../compiler/vendor/enet/enet.dyn#L42)

```dyn
pub fn packet_destroy(packet: Packet)
```

[Source](../../compiler/vendor/enet/enet.dyn#L43)

```dyn
pub fn disconnect(peer: Peer)
```

[Source](../../compiler/vendor/enet/enet.dyn#L57)

Numeric IPv4 only. Use "0.0.0.0" to accept connections on all interfaces.
channels must be 1..255. No DNS lookup or hidden filesystem/network work.

```dyn
pub fn listen_at_owned(ip: []const u8, port: u16, peers: usize, channels: usize, buffer: []u8) Host
```

[Source](../../compiler/vendor/enet/enet.dyn#L61)

```dyn
pub fn client_channels_owned(peers: usize, channels: usize) Host
```

[Source](../../compiler/vendor/enet/enet.dyn#L62)

```dyn
pub fn connect_channels(host: Host, ip: []const u8, port: u16, channels: usize, buffer: []u8) Peer
```

[Source](../../compiler/vendor/enet/enet.dyn#L68)

Graceful disconnect is asynchronous. Continue service until Disconnected or
an application deadline, then destroy the host. Event.data carries the reason.

```dyn
pub fn disconnect_with_reason(peer: Peer, reason: u32)
```
