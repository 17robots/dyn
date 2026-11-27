#!/usr/bin/env python3
"""DER/PEM result, sticky cursor and arena rollback contracts (debug/release)."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())

SOURCE = r'''use parse "std/parse"
use der "std/crypto/der"
use pem "std/crypto/pem"
use certificate "std/crypto/certificate"
use mem "std/mem"
use strings "std/strings"
use "std/bytes"
fn check(ok: bool) { if !ok { #panic("DER/PEM result regression") } }
enum Kind { Ok, InvalidInput, Capacity, Unsupported }
struct Failure { kind: Kind, offset: usize }
fn failure_of(err: parse.ParseErr) Failure {
 case err {
  .Invalid(at) => { return Failure{ kind: Kind.InvalidInput, offset: at } }
  .TooLarge(at) => { return Failure{ kind: Kind.Capacity, offset: at } }
  .Unsupported(at) => { return Failure{ kind: Kind.Unsupported, offset: at } }
 }
}
fn certificate_failure(encoded: []const u8) Failure {
  _ = certificate.parse(encoded) catch err { return failure_of(err) }
  #panic("certificate parse should fail")
}
fn next_failure(cursor: *der.Cursor) Failure {
  _ = der.next(cursor) catch err {
    check(cursor.ended)
    return failure_of(err)
  }
  #panic("der next should fail")
}
fn pem_failure(arena: *mem.Arena, input: []const u8) Failure {
  _ = pem.decode(arena, input) catch err { return failure_of(err) }
  #panic("pem decode should fail")
}
fn next(cursor: *der.Cursor) der.Element {
  return der.next(cursor) catch { #panic("der next") }
}
fn main() {
  certificate_bytes:[10]u8=[48,8,48,0,48,0,3,2,0,170]
  parsed:=certificate.parse(certificate_bytes[..]) catch { #panic("parse") }
  check(parsed.signature_bits[0]==170)
  for i in 0..10 {
    broken:=certificate_failure(certificate_bytes[..i])
    check(broken.kind==Kind.InvalidInput && broken.offset<=i)
  }
  certificate_bytes[0]=49
  check(certificate_failure(certificate_bytes[..]).offset==0)
  certificate_bytes[0]=48
  certificate_bytes[8]=1
  check(certificate_failure(certificate_bytes[..]).offset==8)

  c: der.Cursor
  _ = next(&c)
  check(c.ended && der.finished(&c))
  c = der.cursor("\x30\x03\x02\x01\x07")
  element := next(&c)
  check(!c.ended && element.tag == 48 && element.encoded.len == 5 && der.finished(&c))
  child := der.enter(element)
  check(next(&child).content[0] == 7 && der.finished(&child))
  _ = next(&c)
  check(c.ended && c.start == 5 && der.finished(&c))
  storage: [4096]u8
  arena := mem.arena_from_buffer(storage[..])
  prefix := mem.push_bytes(arena, 7)
  prefix[0] = 42
  mark := mem.arena_mark(arena)
  valid := pem.decode(arena, "prefix\n-----BEGIN TEST-----\nAQID\n-----END TEST-----\ntail") catch { #panic("pem") }
  check(bytes.equal(valid.label, "TEST") && valid.consumed == 52)
  check(valid.data.len == 3)
  mem.arena_rewind(arena, mark)
  empty := pem.decode(arena, "-----BEGIN TEST-----\n-----END TEST-----") catch { #panic("pem") }
  check(empty.data.len == 0 && bytes.equal(empty.label, "TEST"))
  mem.arena_rewind(arena, mark)
  bad := pem_failure(arena, "-----BEGIN TEST-----\n!!!!\n-----END TEST-----")
  check(mem.arena_mark(arena) == mark && prefix[0] == 42 && bad.offset == 21 && bad.kind == Kind.InvalidInput)

  z: der.Element
  p: pem.Block
  check(z.content.len == 0)
  check(p.data.len == 0)
  _ = next(&c)
  malformed: [6][]const u8 = ["\x02", "\x1f\x00", "\x02\x80", "\x02\x82\x01", "\x02\x81\x00", "\x02\x03\x01"]
  offsets: [6]usize = [0, 0, 1, 1, 2, 2]
  for i in 0..6 {
    c = der.cursor(malformed[i])
    failure := next_failure(&c)
    check(failure.kind == Kind.InvalidInput && failure.offset == offsets[i] && !der.finished(&c))
    c.source = "\x02\x01\x07"
    again := next_failure(&c)
    check(again.kind == failure.kind && again.offset == failure.offset && c.offset == 0)
  }
  c = der.Cursor{ offset: #max(usize) }
  check(next_failure(&c).kind == Kind.InvalidInput)
  c = der.cursor("\x02\x89\x01\x01\x01\x01\x01\x01\x01\x01\x01")
  check(next_failure(&c).kind == Kind.Capacity)
  failures: [6][]const u8 = ["", "-----BEGIN -----\n", "-----BEGIN TEST-----x", "-----BEGIN TEST-----\nAQID\n-----END NO-----", "-----BEGIN TEST-----\nAQID", "-----BEGIN TEST-----\nA\n-----END TEST-----"]
  for input in failures {
    failure := pem_failure(arena, input)
    check(failure.kind == Kind.InvalidInput && failure.offset <= input.len)
    check(mem.arena_mark(arena) == mark && prefix[0] == 42)
  }

  complete: []const u8 = "\x30\x03\x02\x01\x07"
  for n in 1..5 {
    truncated := der.cursor(complete[..n])
    short := next_failure(&truncated)
    check(short.kind == Kind.InvalidInput)
    check(next_failure(&truncated).offset == short.offset)
  }
  arena.poison_on_rewind = true
  malformed_pem: []const u8 = "-----BEGIN TEST-----\nAQID\n-----END WRONG-----"
  rejected := pem_failure(arena, malformed_pem)
  check(rejected.offset == 26 && rejected.kind == Kind.InvalidInput && mem.arena_mark(arena) == mark && prefix[0] == 42)

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
