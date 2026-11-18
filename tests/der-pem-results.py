#!/usr/bin/env python3
"""DER/PEM result, sticky cursor and arena rollback contracts (debug/release)."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())

SOURCE = r'''use "std/fail"
use "std/crypto/der" der
use "std/crypto/pem" pem
use "std/crypto/certificate" certificate
use "std/mem" mem
use "std/strings" strings
use "std/bytes"
fn check(ok: bool) { if !ok { #panic("DER/PEM result regression") } }
fn certificate_failure(encoded: []const u8) fail.Failure {
  status: fail.Status
  value := certificate.parse(&status, encoded)
  check(status.failed && #len(value.encoded) == 0)
  return status.failure
}
fn next_failure(cursor: *der.Cursor) fail.Failure {
  status: fail.Status
  _ = der.next(&status, cursor)
  check(status.failed && cursor.ended)
  return status.failure
}
fn pem_failure(arena: *mem.Arena, input: []const u8) fail.Failure {
  status: fail.Status
  block := pem.decode(arena, &status, input)
  check(status.failed && #len(block.data) == 0 && #len(block.label) == 0 && block.consumed == 0)
  return status.failure
}
fn main() {
  status := fail.Status{ on_failure: fail.panic_on_failure }
  certificate_bytes:[10]u8=[48,8,48,0,48,0,3,2,0,170]
  parsed:=certificate.parse(&status, certificate_bytes[..])
  check(parsed.signature_bits[0]==170)
  for i in 0..10 {
    broken:=certificate_failure(certificate_bytes[..i])
    check(broken.kind==fail.Kind.InvalidInput && broken.offset<=i)
  }
  certificate_bytes[0]=49
  check(certificate_failure(certificate_bytes[..]).offset==0)
  certificate_bytes[0]=48
  certificate_bytes[8]=1
  check(certificate_failure(certificate_bytes[..]).offset==8)

  c: der.Cursor
  _ = der.next(&status, &c)
  check(c.ended && der.finished(&c))
  c = der.cursor("\x30\x03\x02\x01\x07")
  element := der.next(&status, &c)
  check(!c.ended && element.tag == 48 && #len(element.encoded) == 5 && der.finished(&c))
  child := der.enter(element)
  check(der.next(&status, &child).content[0] == 7 && der.finished(&child))
  _ = der.next(&status, &c)
  check(c.ended && c.start == 5 && der.finished(&c))
  storage: [4096]u8
  arena := mem.arena_from_buffer(storage[..])
  prefix := mem.push_bytes(arena, 7)
  prefix[0] = 42
  mark := mem.arena_mark(arena)
  valid := pem.decode(arena, &status, "prefix\n-----BEGIN TEST-----\nAQID\n-----END TEST-----\ntail")
  check(bytes.equal(valid.label, "TEST") && valid.consumed == 52)
  check(#len(valid.data) == 3)
  mem.arena_rewind(arena, mark)
  empty := pem.decode(arena, &status, "-----BEGIN TEST-----\n-----END TEST-----")
  check(#len(empty.data) == 0 && bytes.equal(empty.label, "TEST"))
  mem.arena_rewind(arena, mark)
  bad := pem_failure(arena, "-----BEGIN TEST-----\n!!!!\n-----END TEST-----")
  check(mem.arena_mark(arena) == mark && prefix[0] == 42 && bad.offset == 21 && bad.kind == fail.Kind.InvalidInput)

  z: der.Element
  p: pem.Block
  check(#len(z.content) == 0)
  check(#len(p.data) == 0)
  _ = der.next(&status, &c)
  malformed: [6][]const u8 = ["\x02", "\x1f\x00", "\x02\x80", "\x02\x82\x01", "\x02\x81\x00", "\x02\x03\x01"]
  offsets: [6]usize = [0, 0, 1, 1, 2, 2]
  for i in 0..6 {
    c = der.cursor(malformed[i])
    failure := next_failure(&c)
    check(failure.kind == fail.Kind.InvalidInput && failure.offset == offsets[i] && !der.finished(&c))
    c.source = "\x02\x01\x07"
    again := next_failure(&c)
    check(again.kind == failure.kind && again.offset == failure.offset && c.offset == 0)
  }
  c = der.Cursor{ offset: #max(usize) }
  check(next_failure(&c).kind == fail.Kind.InvalidInput)
  c = der.cursor("\x02\x89\x01\x01\x01\x01\x01\x01\x01\x01\x01")
  check(next_failure(&c).kind == fail.Kind.Overflow)
  failures: [6][]const u8 = ["", "-----BEGIN -----\n", "-----BEGIN TEST-----x", "-----BEGIN TEST-----\nAQID\n-----END NO-----", "-----BEGIN TEST-----\nAQID", "-----BEGIN TEST-----\nA\n-----END TEST-----"]
  for input in failures {
    failure := pem_failure(arena, input)
    check(failure.kind == fail.Kind.InvalidInput && failure.offset <= #len(input))
    check(mem.arena_mark(arena) == mark && prefix[0] == 42)
  }

  complete: []const u8 = "\x30\x03\x02\x01\x07"
  for n in 1..5 {
    truncated := der.cursor(complete[..n])
    short := next_failure(&truncated)
    check(short.kind == fail.Kind.InvalidInput)
    check(next_failure(&truncated).offset == short.offset)
  }
  arena.poison_on_rewind = true
  malformed_pem: []const u8 = "-----BEGIN TEST-----\nAQID\n-----END WRONG-----"
  rejected := pem_failure(arena, malformed_pem)
  check(rejected.offset == 26 && rejected.kind == fail.Kind.InvalidInput && mem.arena_mark(arena) == mark && prefix[0] == 42)

}
'''

with tempfile.TemporaryDirectory(prefix='dyn-der-pem-results-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE, encoding='utf-8')
    output = project / ('program.exe' if os.name == 'nt' else 'program')
    for release in (False, True):
        subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet',
                        '--output', str(output)] + (['--release'] if release else []),
                       check=True, timeout=90)
        subprocess.run([str(output)], check=True, timeout=15)
print('PASS DER/PEM results, EOF, sticky errors and rollback (debug/release)')
