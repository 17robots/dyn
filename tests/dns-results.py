#!/usr/bin/env python3
"""Independent DNS wire goldens for arena result ownership; bounded, offline."""
import os
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build'/'dyn-release')).resolve())


def name(text):
    return b''.join(bytes([len(label)]) + label.encode() for label in text.split('.')) + b'\0'


def rr(owner, kind, payload):
    return owner + struct.pack('!HHIH', kind, 1, 60, len(payload)) + payload


def packet(kind, records, flags=0x8180):
    return struct.pack('!6H', 7, flags, 1, len(records), 0, 0) + name('example.test') + struct.pack('!HH', kind, 1) + b''.join(records)


def literal(data):
    return '[' + ','.join(map(str, data)) + ']'


owner = b'\xc0\x0c'
a = rr(owner, 1, bytes([1, 2, 3, 4]))
b = rr(owner, 1, bytes([5, 6, 7, 8]))
v6 = rr(owner, 28, bytes(range(16)))
question_end = 12 + len(name('example.test')) + 4
cases = [
    ('multi_a', 4, packet(1, [a, b]), 2, None),
    ('multi_aaaa', 6, packet(28, [v6, rr(owner, 28, bytes(range(16, 32)))]), 2, None),
    ('cname_order', 4, packet(1, [rr(name('target.test'), 1, bytes([1,2,3,4])), rr(owner, 5, name('target.test'))]), 1, None),
    ('unrelated', 4, packet(1, [rr(name('other.test'), 1, bytes([9]*4)), a]), 1, None),
    ('zero', 4, packet(1, []), 0, None),
    ('zero_aaaa', 6, packet(28, []), 0, None),
    ('bad_question_kind', 4, packet(28, [a]), None, question_end - 4),
    ('bad_identifier', 4, bytes([0,8]) + packet(1, [a])[2:], None, 0),
    ('not_response', 4, packet(1, [a], 0x0180), None, 2),
    ('second_short', 4, packet(1, [a, b])[:-1], None, question_end + len(a)),
    ('second_aaaa', 6, packet(28, [v6, v6])[:-1], None, question_end + len(v6)),
    ('second_owner', 4, packet(1, [a, b'\xc0\xff']), None, question_end + len(a)),
    ('second_length', 4, packet(1, [a, rr(owner, 1, bytes(3))]), None, question_end + len(a)),
    ('second_alias', 4, packet(1, [a, rr(owner, 5, b'\xc0\xff')]), None, question_end + len(a)),
    ('short_header', 4, b'\0'*11, None, 11),
    ('bad_flags', 4, packet(1, [a], 0x8380), None, 2),
    ('nxdomain', 4, packet(1, [], 0x8183), None, 3),
    ('cycle', 4, packet(1, [rr(owner, 5, owner)]), None, None),
    ('conflicting_alias', 4, packet(1, [rr(owner, 5, name('one.test')), rr(owner, 5, name('two.test'))]), None, question_end + len(rr(owner, 5, name('one.test')))),
]
source = '''use dns "std/net/dns"
use "std/fail"
use io "std/io"
use mem "std/mem"
use errors "std/io"
use net "std/net"
fn require(ok: bool) { if !ok { #panic("DNS result contract") } }
// Status-shaped wrappers, so each case reads as one call and one check.
fn parse4(arena: *mem.Arena, status: *fail.Status, data: []const u8, id: u16, name: []const u8) []dns.Ipv4 {
  empty: []dns.Ipv4
  result := dns.parse_ipv4(arena, data, id, name) catch err {
    fail.set(status, io.failure_of(err, "", ""))
    return empty
  }
  return result
}
fn parse6(arena: *mem.Arena, status: *fail.Status, data: []const u8, id: u16, name: []const u8) []dns.Ipv6 {
  empty: []dns.Ipv6
  result := dns.parse_ipv6(arena, data, id, name) catch err {
    fail.set(status, io.failure_of(err, "", ""))
    return empty
  }
  return result
}
fn query4(arena: *mem.Arena, status: *fail.Status, name: []const u8, id: u16) []u8 {
  empty: []u8
  result := dns.query_ipv4(arena, name, id) catch err {
    fail.set(status, io.failure_of(err, "", ""))
    return empty
  }
  return result
}
fn query6(arena: *mem.Arena, status: *fail.Status, name: []const u8, id: u16) []u8 {
  empty: []u8
  result := dns.query_ipv6(arena, name, id) catch err {
    fail.set(status, io.failure_of(err, "", ""))
    return empty
  }
  return result
}
fn resolve4(arena: *mem.Arena, status: *fail.Status, name: []const u8, server: *const net.Ipv4Address, timeout: i32) []dns.Ipv4 {
  empty: []dns.Ipv4
  result := dns.resolve_ipv4(arena, name, server, timeout) catch err {
    fail.set(status, io.failure_of(err, "", ""))
    return empty
  }
  return result
}
fn resolve6(arena: *mem.Arena, status: *fail.Status, name: []const u8, server: *const net.Ipv4Address, timeout: i32) []dns.Ipv6 {
  empty: []dns.Ipv6
  result := dns.resolve_ipv6(arena, name, server, timeout) catch err {
    fail.set(status, io.failure_of(err, "", ""))
    return empty
  }
  return result
}
'''
for label, family, data, count, offset in cases:
    source += f'''fn case_{label}() {{
  data: [{len(data)}]u8 = {literal(data)}
  backing: [1024 + mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(backing[..])
  arena.poison_on_rewind = true
  prefix := mem.push_bytes(arena, 3)
  prefix[0] = 42
  mark := mem.arena_mark(arena)
  status: fail.Status
  result := parse{family}(arena, &status, data[..], 7, "example.test")
'''
    if count is not None:
        source += f'  require(!status.failed && result.len == {count})\n'
        if count:
            if family == 4:
                source += '  require(result[0].a == 1 && result[0].d == 4)\n'
                if count == 2:
                    source += '  require(result[1].a == 5 && result[1].d == 8)\n'
            else:
                source += '  for i in 0..16 { require(result[0].bytes[i] == #cast(u8,i) && result[1].bytes[i] == #cast(u8,i+16)) }\n'
            source += '  require(mem.arena_mark(arena) > mark)\n'
        else:
            source += '  require(mem.arena_mark(arena) == mark)\n'
    else:
        source += '  require(status.failed && result.len == 0 && mem.arena_mark(arena) == mark)\n'
        if label == 'nxdomain':
            source += '  require(status.failure.kind == fail.Kind.NotFound)\n'
        else:
            source += '  require(status.failure.kind == fail.Kind.InvalidInput && status.failure.native == 0)\n'
    source += '  require(prefix[0] == 42)\n'
    if count is None:
        source += '  for i in mark..arena.data.len { require(arena.data[i] == 0) }\n'
    source += '}\n'
data = packet(1, [a, b])
source += f'''fn aliases() {{
  backing: [1024 + mem.ArenaBufferOverhead]u8
  data: [{len(data)}]u8 = {literal(data)}
  arena := mem.arena_from_buffer(backing[..])
  payload := arena.data[mem.ArenaHeader..]
  for i in 0..data.len {{ payload[16+i] = data[i] }}
  arena.poison_on_rewind = true
  status: fail.Status
  result := parse4(arena, &status, payload[16..16+data.len], 7, "example.test")
  require(status.failed && result.len == 0 && mem.arena_mark(arena) == mem.ArenaHeader)
  for i in 0..data.len {{ require(payload[16+i] == data[i]) }}
  text := "example.test"
  for i in 0..text.len {{ payload[i] = text[i] }}
  overlapping: fail.Status
  result = parse4(arena, &overlapping, data[..], 7, payload[..text.len])
  require(overlapping.failed && mem.arena_mark(arena) == mem.ArenaHeader)
  inside: fail.Status
  query := query4(arena, &inside, payload[..text.len], 7)
  require(query.len == 0 && inside.failure.kind == fail.Kind.InvalidInput && mem.arena_mark(arena) == mem.ArenaHeader)
  for i in 0..text.len {{ require(payload[i] == text[i]) }}
  server := net.ipv4(127,0,0,1,53)
  rejected4: fail.Status
  rejected6: fail.Status
  _ = resolve4(arena, &rejected4, payload[..text.len], &server, 0)
  _ = resolve6(arena, &rejected6, payload[..text.len], &server, 0)
  require(rejected4.failed && rejected6.failed && mem.arena_mark(arena) == mem.ArenaHeader)
  invalid4: fail.Status
  invalid6: fail.Status
  _ = resolve4(arena, &invalid4, "", &server, 0)
  _ = resolve6(arena, &invalid6, "", &server, 0)
  require(invalid4.failed && invalid6.failed && mem.arena_mark(arena) == mem.ArenaHeader)
  // Borrowing a live prefix is safe; output is after it.
  _ = mem.push_bytes(arena, text.len)
  borrowed: fail.Status
  result = parse4(arena, &borrowed, data[..], 7, payload[..text.len])
  require(!borrowed.failed && result.len == 2)
  building: fail.Status
  built4 := query4(arena, &building, "example.test", 7)
  built6 := query6(arena, &building, "example.test", 7)
  require(!building.failed && built4.len == 30 && built6.len == 30)
  require(built4[27] == 1 && built6[27] == 28)
  mark := mem.arena_mark(arena)
  bad: fail.Status
  invalid := query4(arena, &bad, "bad..name", 7)
  require(invalid.len == 0 && bad.failure.kind == fail.Kind.InvalidInput && mem.arena_mark(arena) == mark)
}}
fn main() {{
'''
source += ''.join(f'  case_{case[0]}()\n' for case in cases) + '  aliases()\n}\n'
exhaustion = f'''use dns "std/net/dns"
use "std/fail"
use mem "std/mem"
fn main() {{
  data: [{len(data)}]u8 = {literal(data)}
  backing: [1 + mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(backing[..])
  arena = mem.arena_from_buffer(arena.data[..mem.ArenaHeader + 1])
  _ = dns.parse_ipv4(arena, data[..], 7, "example.test") catch {{ return }}
}}
'''
with tempfile.TemporaryDirectory(prefix='dyn-dns-results-') as temporary:
    root = Path(temporary)
    project = root/'source'
    project.mkdir()
    for mode in ('--debug', '--release'):
        for label, program in (('goldens', source), ('exhaustion', exhaustion)):
            (project/'main.dyn').write_text(program)
            output = root/('program.exe' if os.name == 'nt' else 'program')
            subprocess.run([DYN, 'build', str(project), mode, '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=90)
            result = subprocess.run([str(output)], capture_output=True, timeout=15)
            if label == 'goldens':
                assert result.returncode == 0, (mode, result.stdout, result.stderr)
            else:
                assert result.returncode != 0, (mode, 'arena exhaustion did not panic')
                assert b'arena exhausted' in result.stderr.lower(), (mode, result.stderr)
    print('PASS DNS arena wire goldens/rollback/aliases/zero/exhaustion (debug/release)')
