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
source = '''use "std/net/dns" dns
use "std/mem" mem
use "std/errors" errors
use "std/net" net
fn require(ok: bool) { if !ok { #panic("DNS result contract") } }
'''
for label, family, data, count, offset in cases:
    source += f'''fn case_{label}() {{
  data: [{len(data)}]u8 = {literal(data)}
  backing: [1024 + mem.ArenaBufferOverhead]u8 = []
  arena := mem.arena_from_buffer(backing[..])
  arena.poison_on_rewind = true
  prefix := mem.push_bytes_uninit(arena, 3)
  prefix[0] = 42
  mark := mem.arena_mark(arena)
  result := dns.parse_ipv{family}(arena, data[..], 7, "example.test")
'''
    if count is not None:
        source += f'  require(result.ok && #len(result.value) == {count})\n'
        if count:
            if family == 4:
                source += '  require(result.value[0].a == 1 && result.value[0].d == 4)\n'
                if count == 2:
                    source += '  require(result.value[1].a == 5 && result.value[1].d == 8)\n'
            else:
                source += '  for i in 0..16 { require(result.value[0].bytes[i] == #cast(u8,i) && result.value[1].bytes[i] == #cast(u8,i+16)) }\n'
            source += '  require(mem.arena_mark(arena) > mark)\n'
        else:
            source += '  require(mem.arena_mark(arena) == mark)\n'
    else:
        source += '  require(!result.ok && #len(result.value) == 0 && mem.arena_mark(arena) == mark)\n'
        if offset is not None:
            source += f'  require(result.offset == {offset})\n'
        if label == 'nxdomain':
            source += '  require(result.kind == errors.Kind.NotFound && result.error == -3)\n'
        else:
            source += '  require(result.kind == errors.Kind.InvalidInput && result.error == 0)\n'
    source += '  require(prefix[0] == 42)\n'
    if count is None:
        source += '  for i in mark..#len(arena.data) { require(arena.data[i] == 0) }\n'
    source += '}\n'
data = packet(1, [a, b])
source += f'''fn aliases() {{
  backing: [1024 + mem.ArenaBufferOverhead]u8 = []
  data: [{len(data)}]u8 = {literal(data)}
  arena := mem.arena_from_buffer(backing[..])
  payload := arena.data[mem.ArenaHeader..]
  for i in 0..#len(data) {{ payload[16+i] = data[i] }}
  arena.poison_on_rewind = true
  result := dns.parse_ipv4(arena, payload[16..16+#len(data)], 7, "example.test")
  require(!result.ok && #len(result.value) == 0 && mem.arena_mark(arena) == mem.arena_start(arena))
  for i in 0..#len(data) {{ require(payload[16+i] == data[i]) }}
  text := "example.test"
  for i in 0..#len(text) {{ payload[i] = text[i] }}
  result = dns.parse_ipv4(arena, data[..], 7, payload[..#len(text)])
  require(!result.ok && mem.arena_mark(arena) == mem.arena_start(arena))
  query := dns.query_ipv4(arena, payload[..#len(text)], 7)
  require(#len(query) == 0 && mem.arena_mark(arena) == mem.arena_start(arena))
  for i in 0..#len(text) {{ require(payload[i] == text[i]) }}
  server := net.ipv4(127,0,0,1,53)
  rejected4 := dns.resolve_ipv4(arena, payload[..#len(text)], &server, 0)
  rejected6 := dns.resolve_ipv6(arena, payload[..#len(text)], &server, 0)
  require(!rejected4.ok && !rejected6.ok && mem.arena_mark(arena) == mem.arena_start(arena))
  invalid4 := dns.resolve_ipv4(arena, "", &server, 0)
  invalid6 := dns.resolve_ipv6(arena, "", &server, 0)
  require(!invalid4.ok && !invalid6.ok && mem.arena_mark(arena) == mem.arena_start(arena))
  // Borrowing a live prefix is safe; output is after it.
  _ = mem.push_bytes_uninit(arena, #len(text))
  result = dns.parse_ipv4(arena, data[..], 7, payload[..#len(text)])
  require(result.ok && #len(result.value) == 2)
  query4 := dns.query_ipv4(arena, "example.test", 7)
  query6 := dns.query_ipv6(arena, "example.test", 7)
  require(#len(query4) == 30 && #len(query6) == 30)
  require(query4[27] == 1 && query6[27] == 28)
  mark := mem.arena_mark(arena)
  invalid := dns.query_ipv4(arena, "bad..name", 7)
  require(#len(invalid) == 0 && mem.arena_mark(arena) == mark)
}}
fn main() {{
'''
source += ''.join(f'  case_{case[0]}()\n' for case in cases) + '  aliases()\n}\n'
exhaustion = f'''use "std/net/dns" dns
use "std/mem" mem
fn main() {{
  data: [{len(data)}]u8 = {literal(data)}
  backing: [1 + mem.ArenaBufferOverhead]u8 = []
  arena := mem.arena_from_buffer(backing[..])
  arena = mem.arena_from_buffer(arena.data[..mem.ArenaHeader + 1])
  _ = dns.parse_ipv4(arena, data[..], 7, "example.test")
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
    print('PASS DNS arena wire goldens/offsets/rollback/aliases/zero/exhaustion (debug/release)')
