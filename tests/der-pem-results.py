#!/usr/bin/env python3
"""DER/PEM result, sticky cursor and arena rollback contracts (debug/release)."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())

SOURCE = r'''use "std/crypto/der" der
use "std/crypto/pem" pem
use "std/crypto/certificate" certificate
use "std/mem" mem
use "std/errors" errors
use "std/strings" strings
fn check(ok: bool) { if !ok { #panic("DER/PEM result regression") } }
fn main() {
  certificate_bytes:[10]u8=[48,8,48,0,48,0,3,2,0,170]
  certificate_result:=certificate.parse(certificate_bytes[..])
  check(certificate_result.ok && certificate_result.kind==errors.Kind.None && certificate_result.error==0 && certificate_result.value.signature_bits[0]==170)
  for i in 0..10 {
    broken:=certificate.parse(certificate_bytes[..i])
    check(!broken.ok && broken.kind==errors.Kind.InvalidInput && broken.error==0 && #len(broken.value.encoded)==0 && broken.offset<=i)
  }
  certificate_bytes[0]=49
  check(certificate.parse(certificate_bytes[..]).offset==0)
  certificate_bytes[0]=48
  certificate_bytes[8]=1
  check(certificate.parse(certificate_bytes[..]).offset==8)

  c: der.Cursor
  check(!der.next(&c).ok && der.finished(&c))
  c = der.cursor("\x30\x03\x02\x01\x07")
  element := der.next(&c)
  check(element.ok && element.value.tag == 48 && #len(element.value.encoded) == 5 && der.finished(&c))
  child := der.enter(element.value)
  check(der.next(&child).value.content[0] == 7 && der.finished(&child))
  eof := der.next(&c)
  check(!eof.ok && eof.kind == errors.Kind.None && eof.error == 0 && eof.offset == 5 && der.finished(&c))
  storage: [4096]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  prefix := mem.push_bytes_uninit(arena, 7)
  prefix[0] = 42
  mark := mem.arena_mark(arena)
  valid := pem.decode(arena, "prefix\n-----BEGIN TEST-----\nAQID\n-----END TEST-----\ntail")
  check(valid.ok && strings.equal(valid.label, "TEST") && valid.consumed == 52)
  check(#len(valid.value) == 3)
  mem.arena_rewind(arena, mark)
  empty := pem.decode(arena, "-----BEGIN TEST-----\n-----END TEST-----")
  check(empty.ok && #len(empty.value) == 0 && strings.equal(empty.label, "TEST") && empty.kind == errors.Kind.None && empty.error == 0)
  mem.arena_rewind(arena, mark)
  bad := pem.decode(arena, "-----BEGIN TEST-----\n!!!!\n-----END TEST-----")
  check(!bad.ok)
  check(mem.arena_mark(arena) == mark && prefix[0] == 42 && #len(bad.value) == 0 && bad.offset == 21 && bad.kind == errors.Kind.InvalidInput && bad.error == 0)
  
  z: der.Result
  p: pem.Result
  check(!z.ok && z.kind == errors.Kind.None && z.error == 0 && z.offset == 0 && #len(z.value.content) == 0)
  check(!p.ok && p.kind == errors.Kind.None && p.error == 0 && p.offset == 0 && #len(p.value) == 0)
  check(der.next(&c).kind == errors.Kind.None)
  malformed: [6][]const u8 = ["\x02", "\x1f\x00", "\x02\x80", "\x02\x82\x01", "\x02\x81\x00", "\x02\x03\x01"]
  offsets: [6]usize = [0, 0, 1, 1, 2, 2]
  for i in 0..6 {
    c = der.cursor(malformed[i])
    failure := der.next(&c)
    check(!failure.ok && failure.kind == errors.Kind.InvalidInput && failure.error == 0 && failure.offset == offsets[i] && !der.finished(&c))
    c.source = "\x02\x01\x07"
    again := der.next(&c)
    check(!again.ok && again.kind == failure.kind && again.offset == failure.offset && c.offset == 0)
  }
  c = der.Cursor{ offset: ~#cast(usize, 0) }
  check(der.next(&c).kind == errors.Kind.InvalidInput)
  c = der.cursor("\x02\x89\x01\x01\x01\x01\x01\x01\x01\x01\x01")
  check(der.next(&c).kind == errors.Kind.Overflow)
  failures: [6][]const u8 = ["", "-----BEGIN -----\n", "-----BEGIN TEST-----x", "-----BEGIN TEST-----\nAQID\n-----END NO-----", "-----BEGIN TEST-----\nAQID", "-----BEGIN TEST-----\nA\n-----END TEST-----"]
  for input in failures {
    result := pem.decode(arena, input)
    check(!result.ok && result.kind == errors.Kind.InvalidInput && result.error == 0 && #len(result.value) == 0 && #len(result.label) == 0 && result.consumed == 0 && result.offset <= #len(input))
    check(mem.arena_mark(arena) == mark && prefix[0] == 42)
  }

  complete: []const u8 = "\x30\x03\x02\x01\x07"
  for n in 1..5 {
    truncated := der.cursor(complete[..n])
    short := der.next(&truncated)
    check(!short.ok && short.kind == errors.Kind.InvalidInput && short.error == 0)
    check(der.next(&truncated).offset == short.offset)
  }
  arena.poison_on_rewind = true
  malformed_pem: []const u8 = "-----BEGIN TEST-----\nAQID\n-----END WRONG-----"
  rejected := pem.decode(arena, malformed_pem)
  check(rejected.offset == 26 && rejected.kind == errors.Kind.InvalidInput && mem.arena_mark(arena) == mark && prefix[0] == 42)

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
