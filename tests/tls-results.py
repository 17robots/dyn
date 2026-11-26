#!/usr/bin/env python3
"""TLS portable results and complete subjects, with independent libcrypto oracle."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
WORKSPACE_TESTS = Path(os.environ.get('DYN_WORKSPACE_TESTS', ROOT / 'tests/fixtures')).resolve()
CC = shlex.split(os.environ.get('CC', 'cc'))

# Construct a real certificate independently of Dyn's TLS provider. Repeated OUs
# exceed the former fixed 1024-byte subject buffer; oneline is the full oracle.
FIXTURE = r'''
#include <openssl/x509.h>
#include <openssl/pem.h>
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    if (argc != 3) return 1;
    X509 *x = X509_new();
    EVP_PKEY *key = EVP_PKEY_Q_keygen(NULL, NULL, "ED25519");
    if (!x || !key) return 2;
    X509_NAME *name = X509_get_subject_name(x);
    for (int i = 0; i < 40; ++i) {
        char value[64];
        snprintf(value, sizeof value, "independent-unit-%02d-abcdefghijklmnopqrstuvwxyz", i);
        if (!X509_NAME_add_entry_by_txt(name, "OU", MBSTRING_ASC,
                (unsigned char *)value, -1, -1, 0)) return 3;
    }
    if (!X509_set_version(x, 2) || !ASN1_INTEGER_set(X509_get_serialNumber(x), 1)
        || !X509_gmtime_adj(X509_getm_notBefore(x), 0)
        || !X509_gmtime_adj(X509_getm_notAfter(x), 3600)
        || !X509_set_issuer_name(x, name) || !X509_set_pubkey(x, key)
        || !X509_sign(x, key, NULL)) return 4;
    char *text = X509_NAME_oneline(name, NULL, 0);
    if (!text || strlen(text) <= 1023) return 5;
    FILE *pem = fopen(argv[1], "wb"), *oracle = fopen(argv[2], "wb");
    if (!pem || !oracle || !PEM_write_X509(pem, x)) return 6;
    if (fwrite(text, 1, strlen(text), oracle) != strlen(text)) return 7;
    fclose(pem); fclose(oracle);
    OPENSSL_free(text); X509_free(x); EVP_PKEY_free(key);
    return 0;
}
'''

COMMON = r'''
use tls "std/net/tls"
use mem "std/mem"
use io "std/io"
fn check(ok: bool) { if !ok { #panic("TLS result contract") } }
fn invalid(err: io.IoErr) bool {
  case err {
    .InvalidInput => { return true }
    _ => { return false }
  }
}
fn denied(err: io.IoErr) bool {
  case err {
    .PermissionDenied => { return true }
    _ => { return false }
  }
}
fn system(err: io.IoErr, code: isize) bool {
  case err {
    .System(native) => { return native == code }
    _ => { return false }
  }
}
fn provider_code(err: io.IoErr) bool {
  case err {
    .System(native) => { return native != 0 }
    _ => { return false }
  }
}
'''
REAL = COMMON + r'''
#link("crypto")
extern fn bio_new "BIO_new_mem_buf"(data: *const u8, length: i32) rawptr
extern fn bio_free "BIO_free"(bio: rawptr) i32
extern fn read_cert "PEM_read_bio_X509"(bio: rawptr, output: rawptr, password: rawptr, data: rawptr) rawptr
fn connection_err(arena: *mem.Arena) io.IoErr {
  _ = tls.client_connection_create(arena, nil, -1, "host") catch err { return err }
  #panic("connection unexpectedly created")
}
fn config_err(arena: *mem.Arena) io.IoErr {
  _ = tls.server_config_create(arena, "/dyn/no-certificate.pem", "/dyn/no-key.pem") catch err { return err }
  #panic("config unexpectedly created")
}
fn handshake_err() io.IoErr {
  _ = tls.handshake(nil) catch err { return err }
  #panic("handshake unexpectedly succeeded")
}
fn server_handshake_fails() bool {
  _ = tls.server_handshake(nil) catch { return true }
  return false
}
fn shutdown_fails() bool {
  _ = tls.shutdown(nil) catch { return true }
  return false
}
fn alpn_fails() bool {
  tls.set_alpn_protocols(nil, "\x02h2") catch { return true }
  return false
}
fn subject_err(arena: *mem.Arena) io.IoErr {
  _ = tls.certificate_subject(arena, nil) catch err { return err }
  #panic("subject unexpectedly read")
}
fn main() {
  backing: [16384]u8
  mem.fill(backing[..], 165)
  arena := mem.arena_from_buffer(backing[..])
  prefix := mem.push_bytes(arena, 7)
  mark := mem.arena_mark(arena)
  check(invalid(connection_err(arena)))
  provider := config_err(arena)
  check(provider_code(provider) && io.text(provider).len > 0)
  check(invalid(handshake_err()))
  check(server_handshake_fails() && shutdown_fails() && alpn_fails())
  check(invalid(subject_err(arena)) && mem.arena_mark(arena) == mark)
  for byte in prefix { check(byte == 165) }
  pem: []const u8 = PEM
  bio := bio_new(&pem[0], #cast(i32, pem.len))
  check(bio != nil)
  cert := read_cert(bio, nil, nil, nil)
  _ = bio_free(bio)
  check(cert != nil)
  subject := tls.certificate_subject(arena, cert) catch { #panic("certificate subject") }
  check(subject.len > 1023 && mem.equal(subject, ORACLE))
  check(mem.arena_mark(arena) == mark + subject.len)
  tls.certificate_release(&cert)
  tls.certificate_release(&cert)
  check(cert == nil && mem.equal(subject, ORACLE))
  for byte in prefix { check(byte == 165) }
  for byte in arena.data[mem.arena_mark(arena)..] { check(byte == 165) }
}
'''

# Copy the actual provider, replacing only its operation bodies with injected
# results. This keeps all type declarations and unused API signatures exact.
MOCK = COMMON.replace('"std/net/tls"', '"tls"') + r'''
// A want is no failure; the others are: PermissionDenied, or System with the
// provider's code.
struct Outcome { want: tls.Want, count: usize, err: io.IoErr, failed: bool }
fn do_handshake(conn: tls.Connection) Outcome {
  wanted := tls.handshake(conn) catch err { return Outcome{ err: err, failed: true } }
  return Outcome{ want: wanted }
}
fn do_read(conn: tls.Connection, data: []u8) Outcome {
  attempt := tls.read(conn, data) catch err { return Outcome{ err: err, failed: true } }
  return Outcome{ want: attempt.want, count: attempt.count }
}
fn do_write(conn: tls.Connection, data: []const u8) Outcome {
  attempt := tls.write(conn, data) catch err { return Outcome{ err: err, failed: true } }
  return Outcome{ want: attempt.want, count: attempt.count }
}
fn expect(mode: usize, outcome: Outcome) {
  if mode == 1 { check(!outcome.failed && outcome.want == tls.Want.Read) }
  if mode == 2 { check(!outcome.failed && outcome.want == tls.Want.Write) }
  if mode == 3 { check(outcome.failed && denied(outcome.err)) }
  if mode == 4 { check(outcome.failed && system(outcome.err, -1)) }
  check(outcome.count == 0)
}
fn subject_err(arena: *mem.Arena, conn: tls.Certificate) io.IoErr {
  _ = tls.certificate_subject(arena, conn) catch err { return err }
  #panic("subject unexpectedly read")
}
fn main() {
  backing: [mem.ArenaBufferOverhead+32]u8
  mem.fill(backing[..], 165)
  arena := mem.arena_from_buffer(backing[..])
  storage := arena.data[mem.ArenaHeader..mem.ArenaHeader+32]
  _ = mem.push_bytes(arena, 7)
  for mode in 1..5 {
    conn := #cast(rawptr, mode)
    data: [4]u8
    expect(#cast(usize, mode), do_handshake(conn))
    expect(#cast(usize, mode), do_read(conn, data[..]))
    expect(#cast(usize, mode), do_write(conn, "test"))
  }
  tls.set_alpn_protocols(#cast(rawptr, 1), "\x02h2") catch { #panic("alpn") }
  pending := tls.shutdown(#cast(rawptr, 1)) catch { #panic("shutdown") }
  check(pending == tls.Want.Read)
  check(system(subject_err(arena, #cast(rawptr, 1)), -1) && mem.arena_used(arena) == 7)
  for byte in storage { check(byte == 165) }
}
'''

def replace_body(source, name, body):
    start = source.index('{', source.index('pub fn ' + name + '('))
    depth, end = 1, start + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[:start + 1] + '\n' + body + '\n' + source[end - 1:]


def project(root, name, source):
    path = root / name
    path.mkdir()
    (path / 'main.dyn').write_text(source, encoding='utf-8')
    return path


def run(path, release, panic=False):
    output = path / 'program'
    subprocess.run([DYN, 'build', str(path), '--no-cache', '--quiet', '--output', str(output)]
                   + (['--release'] if release else []), cwd=ROOT,
                   env=dict(os.environ, DYN_SDK=str(ROOT)), check=True, timeout=90)
    result = subprocess.run([str(output)], capture_output=True, text=True, timeout=15)
    if panic:
        assert result.returncode == 101 and 'arena exhausted' in result.stderr, result
    else:
        assert result.returncode == 0, (path.name, result.stdout, result.stderr)


with tempfile.TemporaryDirectory(prefix='dyn-tls-results-') as temporary:
    root = Path(temporary)
    native = root / 'fixture.c'
    native.write_text(FIXTURE, encoding='utf-8')
    executable = root / 'fixture'
    subprocess.run(CC + [str(native), '-o', str(executable), '-lcrypto'], check=True, timeout=30)
    pem, oracle = root / 'cert.pem', root / 'subject.txt'
    subprocess.run([str(executable), str(pem), str(oracle)], check=True, timeout=15)
    subject = oracle.read_text()
    assert len(subject.encode()) > 1023
    real_source = REAL.replace('PEM\n', json.dumps(pem.read_text()) + '\n').replace('ORACLE', json.dumps(subject))
    real = project(root, 'real', real_source)
    mock = project(root, 'mock', MOCK)
    wrapper = (ROOT / 'std/net/tls/tls.dyn').read_text().replace('"vendor/openssl/tls"', '"stub"')
    (mock / 'tls').mkdir()
    (mock / 'tls/tls.dyn').write_text(wrapper)
    provider = (ROOT / 'vendor/openssl/tls/tls.dyn').read_text()
    provider = replace_body(provider, 'handshake', '''  mode := #cast(usize, connection)
  if mode == 1 { return Want.Read }
  if mode == 2 { return Want.Write }
  if mode == 3 { fail .PermissionDenied }
  fail io.IoErr.System(-1)''')
    provider = replace_body(provider, 'read', '  _ = destination\nreturn Attempt{ want: try handshake(connection) }')
    provider = replace_body(provider, 'write', '  _ = source\nreturn Attempt{ want: try handshake(connection) }')
    provider = replace_body(provider, 'set_alpn_protocols', '  _ = connection\n_ = protocols')
    provider = replace_body(provider, 'shutdown', '  _ = connection\nreturn Want.Read')
    provider = replace_body(provider, 'subject_text_owned', '''  _ = certificate
  fail io.IoErr.System(-1)''')
    (mock / 'stub').mkdir()
    (mock / 'stub/stub.dyn').write_text(provider)
    for sibling in (ROOT / 'vendor/openssl/tls').glob('*.dyn'):
        if sibling.name != 'tls.dyn':
            (mock / 'stub' / sibling.name).write_text(sibling.read_text())
    sdk = project(root, 'sdk', (WORKSPACE_TESTS / 'sdk-tls-native/main.dyn').read_text())
    # The real certificate also exercises arena exhaustion after provider allocation.
    exhausted = project(root, 'exhausted', real_source[:real_source.index('fn main()')] + '''fn main() {
  backing: [mem.ArenaBufferOverhead]u8
  skip := (16-(#cast(usize,&backing[0]) & 15)) & 15
  arena := mem.arena_from_buffer(backing[skip..skip+mem.ArenaHeader])
  pem: []const u8 = ''' + json.dumps(pem.read_text()) + '''
  bio := bio_new(&pem[0], #cast(i32, pem.len))
  check(bio != nil)
  cert := read_cert(bio, nil, nil, nil)
  _ = bio_free(bio)
  check(cert != nil)
  _ = tls.certificate_subject(arena, cert) catch { return }
}
''')
    for release in (False, True):
        for case in (real, mock, sdk):
            run(case, release)
        run(exhausted, release, panic=True)
        print('PASS TLS results ' + ('release' if release else 'debug') + f'; subject bytes={len(subject.encode())}', flush=True)
