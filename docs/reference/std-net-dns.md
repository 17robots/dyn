# std/net/dns

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

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/net/dns/dns.dyn

[Source](../../compiler/std/net/dns/dns.dyn#L5)

```dyn
pub struct Ipv4 { a: u8, b: u8, c: u8, d: u8 }
```

[Source](../../compiler/std/net/dns/dns.dyn#L6)

```dyn
pub struct Ipv6 { bytes: [16]u8 }
```

[Source](../../compiler/std/net/dns/dns.dyn#L7)

```dyn
pub struct Result { count: usize, error: isize, ok: bool }
```

[Source](../../compiler/std/net/dns/dns.dyn#L60)

```dyn
pub fn query_ipv4(destination: []u8, name: []const u8, identifier: u16) []u8
```

[Source](../../compiler/std/net/dns/dns.dyn#L63)

```dyn
pub fn query_ipv6(destination: []u8, name: []const u8, identifier: u16) []u8
```

[Source](../../compiler/std/net/dns/dns.dyn#L83)

```dyn
pub fn parse_ipv4(packet: []const u8, identifier: u16, name: []const u8, addresses: []Ipv4) Result
```

[Source](../../compiler/std/net/dns/dns.dyn#L87)

```dyn
pub fn parse_ipv6(packet: []const u8, identifier: u16, name: []const u8, addresses: []Ipv6) Result
```

[Source](../../compiler/std/net/dns/dns.dyn#L173)

The server transport address is IPv4; IPv6 refers to AAAA result records.
One deadline covers UDP, TCP connect, framing, and every partial transfer.

```dyn
pub fn resolve_ipv4(name: []const u8, server: *const network.Ipv4Address, addresses: []Ipv4,
                    packet: []u8, timeout_milliseconds: i32) Result
```

[Source](../../compiler/std/net/dns/dns.dyn#L179)

```dyn
pub fn resolve_ipv6(name: []const u8, server: *const network.Ipv4Address, addresses: []Ipv6,
                    packet: []u8, timeout_milliseconds: i32) Result
```
