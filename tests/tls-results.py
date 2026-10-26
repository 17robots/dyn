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
use "std/net/tls" tls
use "std/mem" mem
use "std/errors" errors
fn check(ok: bool) { if !ok { #panic("TLS result contract") } }
'''
REAL = COMMON + r'''
#link("crypto")
extern fn bio_new "BIO_new_mem_buf"(data: *const u8, length: i32) rawptr
extern fn bio_free "BIO_free"(bio: rawptr) i32
extern fn read_cert "PEM_read_bio_X509"(bio: rawptr, output: rawptr, password: rawptr, data: rawptr) rawptr
fn main() {
  z: tls.Result
  c: tls.ContextResult
  n: tls.ConnectionResult
  t: tls.TextResult
  check(!z.ok && z.kind == errors.Kind.None && z.error == 0 && z.detail == tls.ErrorKind.None && z.provider_code == 0 && z.provider_status == 0 && z.count == 0)
  check(!c.ok && c.value == nil && c.error == 0 && c.kind == errors.Kind.None && c.detail == tls.ErrorKind.None && c.provider_code == 0)
  check(!n.ok && n.value == nil && n.error == 0 && n.kind == errors.Kind.None && n.detail == tls.ErrorKind.None && n.provider_code == 0)
  check(!t.ok && #len(t.value) == 0 && t.kind == errors.Kind.None && t.error == 0 && t.provider_code == 0)
  backing: [16384]u8
  mem.fill(backing[..], 165)
  arena := mem.arena_from_buffer(backing[..])
  prefix := mem.push_bytes_uninit(arena, 7)
  mark := mem.arena_mark(arena)
  invalid := tls.client_connection_create(arena, nil, -1, "host")
  check(!invalid.ok && invalid.value == nil && invalid.kind == errors.Kind.InvalidInput && invalid.detail == tls.ErrorKind.InvalidArgument && invalid.error == 0 && invalid.provider_code == 0)
  config := tls.server_config_create(arena, "/dyn/no-certificate.pem", "/dyn/no-key.pem")
  check(!config.ok && config.value == nil && config.kind == errors.Kind.System && config.detail == tls.ErrorKind.Provider && config.error == 0 && config.provider_code != 0)
  bad := tls.handshake(nil)
  check(!bad.ok && bad.kind == errors.Kind.InvalidInput && bad.detail == tls.ErrorKind.InvalidArgument && bad.count == 0 && bad.error == 0 && bad.provider_code == 0 && bad.provider_status == 0)
  check(!tls.server_handshake(nil).ok && !tls.shutdown(nil).ok && !tls.set_alpn_protocols(nil, "\x02h2").ok)
  missing := tls.certificate_subject(arena, nil)
  check(!missing.ok && missing.kind == errors.Kind.InvalidInput && missing.error == 0 && missing.provider_code == 0 && #len(missing.value) == 0 && mem.arena_mark(arena) == mark)
  for byte in prefix { check(byte == 165) }
  pem: []const u8 = PEM
  bio := bio_new(&pem[0], #cast(i32, #len(pem)))
  check(bio != nil)
  cert := read_cert(bio, nil, nil, nil)
  _ = bio_free(bio)
  check(cert != nil)
  subject := tls.certificate_subject(arena, cert)
  check(subject.ok && subject.kind == errors.Kind.None && subject.error == 0 && subject.provider_code == 0 && #len(subject.value) > 1023 && mem.equal(subject.value, ORACLE))
  check(mem.arena_mark(arena) == mark + #len(subject.value))
  tls.certificate_release(&cert)
  tls.certificate_release(&cert)
  check(cert == nil && mem.equal(subject.value, ORACLE))
  for byte in prefix { check(byte == 165) }
  for byte in arena.data[mem.arena_mark(arena)..] { check(byte == 165) }
}
'''

# Copy the actual provider, replacing only its operation bodies with injected
# results. This keeps all type declarations and unused API signatures exact.
MOCK = COMMON.replace('"std/net/tls"', '"tls"') + r'''
fn main() {
  backing: [mem.ArenaBufferOverhead+32]u8
  mem.fill(backing[..], 165)
  arena := mem.arena_from_buffer(backing[..])
  storage := arena.data[mem.ArenaHeader..mem.ArenaHeader+32]
  _ = mem.push_bytes_uninit(arena, 7)
  for mode in 1..5 {
    conn := #cast(rawptr, mode)
    r := tls.handshake(conn)
    data: [4]u8
    rd := tls.read(conn, data[..])
    wr := tls.write(conn, "test")
    check(rd.kind == r.kind && rd.detail == r.detail && rd.error == 0 && rd.provider_code == r.provider_code && rd.provider_status == r.provider_status && rd.count == 0 && !rd.ok)
    check(wr.kind == r.kind && wr.detail == r.detail && wr.error == 0 && wr.provider_code == r.provider_code && wr.provider_status == r.provider_status && wr.count == 0 && !wr.ok)
    expected := errors.Kind.WouldBlock
    if mode == 3 { expected = errors.Kind.PermissionDenied }
    if mode == 4 { expected = errors.Kind.System }
    check(!r.ok && r.kind == expected && r.error == 0 && r.provider_code == 18446744073709551615 && r.provider_status == -7 && r.count == 0)
    if mode == 1 { check(r.detail == tls.ErrorKind.WantRead) }
    if mode == 2 { check(r.detail == tls.ErrorKind.WantWrite) }
    if mode == 3 { check(r.detail == tls.ErrorKind.Verification) }
    if mode == 4 { check(r.detail == tls.ErrorKind.Provider) }
  }
  alpn := tls.set_alpn_protocols(#cast(rawptr, 1), "\x02h2")
  check(alpn.ok && alpn.kind == errors.Kind.None && alpn.detail == tls.ErrorKind.None && alpn.error == 0 && alpn.provider_code == 0)
  pending := tls.shutdown(#cast(rawptr, 1))
  check(!pending.ok && pending.kind == errors.Kind.WouldBlock && pending.detail == tls.ErrorKind.WantRead && pending.error == 0 && pending.provider_status == 0)
  failed := tls.certificate_subject(arena, #cast(rawptr, 1))
  check(!failed.ok && failed.kind == errors.Kind.System && failed.error == 0 && failed.provider_code == 18446744073709551615 && #len(failed.value) == 0 && mem.arena_used(arena) == 7)
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
        assert result.returncode == 101 and 'arena exhausted or alignment invalid' in result.stderr, result
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
  detail := ErrorKind.WantRead
  if mode == 2 { detail = ErrorKind.WantWrite }
  if mode == 3 { detail = ErrorKind.Verification }
  if mode == 4 { detail = ErrorKind.Provider }
  return Result{error: detail, provider_code: 18446744073709551615, provider_status: -7}''')
    provider = replace_body(provider, 'read', '  _ = destination\nreturn handshake(connection)')
    provider = replace_body(provider, 'write', '  _ = source\nreturn handshake(connection)')
    provider = replace_body(provider, 'set_alpn_result', '  _ = connection\n_ = protocols\nreturn Result{ok: true}')
    provider = replace_body(provider, 'shutdown_result', '  _ = connection\nreturn Result{error: ErrorKind.WantRead, provider_status: 0}')
    provider = replace_body(provider, 'subject_text_owned', '  _ = certificate\nreturn SubjectTextResult{provider_code: 18446744073709551615}')
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
  bio := bio_new(&pem[0], #cast(i32, #len(pem)))
  check(bio != nil)
  cert := read_cert(bio, nil, nil, nil)
  _ = bio_free(bio)
  check(cert != nil)
  _ = tls.certificate_subject(arena, cert)
}
''')
    for release in (False, True):
        for case in (real, mock, sdk):
            run(case, release)
        run(exhausted, release, panic=True)
        print('PASS TLS results ' + ('release' if release else 'debug') + f'; subject bytes={len(subject.encode())}', flush=True)
