#!/usr/bin/env python3
"""Native crypto result contracts against published and independent vectors.

AES vectors: NIST zero-key AES-256-GCM. ChaCha bytes were independently
computed with OpenSSL EVP, never with the std wrapper under test.
X25519/Ed25519 vectors: RFC 7748 / RFC 8032.
"""
import os
from pathlib import Path
import subprocess
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get("DYN", ROOT / "build/dyn-release")).resolve())

AEAD = r'''use "std/crypto/aead" aead
use "std/crypto/aes" aes
use "std/mem" mem
use "std/errors" errors
fn check(ok: bool) { if !ok { #panic("fixture failed") } }
fn main() {
 zs: aead.SealResult
 zo: aead.OpenResult
 check(!zs.ok && zs.kind == errors.Kind.None && zs.error == 0 && zs.provider_code == 0 && #len(zs.value.ciphertext) == 0 && #len(zs.value.tag) == 0)
 check(!zo.ok && zo.kind == errors.Kind.None && zo.error == 0 && zo.provider_code == 0 && #len(zo.value) == 0)
 backing: [1024]u8
 mem.fill(backing[..], 165)
 arena := mem.arena_from_buffer(backing[..])
 prefix := mem.push_bytes_uninit(&arena, 7)
 mem.fill(prefix, 77)
 key: [32]u8
 nonce: [12]u8
 plain: [16]u8
 sealed := aes.gcm_seal(&arena, plain[..], "", key[..], nonce[..])
 check(sealed.ok && sealed.kind == errors.Kind.None && sealed.error == 0 && sealed.provider_code == 0)
 check(mem.equal(sealed.value.ciphertext, "\xce\xa7\x40\x3d\x4d\x60\x6b\x6e\x07\x4e\xc5\xd3\xba\xf3\x9d\x18") && mem.equal(sealed.value.tag, "\xd0\xd1\xc8\xa7\x99\x99\x6b\xf0\x26\x5b\x98\xb5\xd4\x8a\xb9\x19"))
 opened := aes.gcm_open(&arena, sealed.value.ciphertext, sealed.value.tag, "", key[..], nonce[..])
 check(opened.ok && mem.equal(opened.value, plain[..]) && mem.arena_used(&arena) == 55)
 mark := mem.arena_mark(&arena)
 sealed.value.tag[0] ^= 1
 bad := aes.gcm_open(&arena, sealed.value.ciphertext, sealed.value.tag, "", key[..], nonce[..])
 check(!bad.ok && bad.kind == errors.Kind.InvalidInput && bad.error == 0 && bad.provider_code == 0 && #len(bad.value) == 0 && mem.arena_used(&arena) == mark)
 for i in mark..mark + 16 { check(backing[i] == 0) }
 for i in 0..7 { check(backing[i] == 77) }
 sealed.value.tag[0] ^= 1
 empty := aes.gcm_seal(&arena, "", "", key[..], nonce[..])
 check(empty.ok && #len(empty.value.ciphertext) == 0 && mem.equal(empty.value.tag, "\x53\x0f\x8a\xfb\xc7\x45\x36\xb9\xa9\x63\xb4\xf1\xc4\xcb\x73\x8b"))
 empty_open := aes.gcm_open(&arena, "", empty.value.tag, "", key[..], nonce[..])
 check(empty_open.ok && #len(empty_open.value) == 0)
 ch := aead.seal(&arena, aead.Cipher.Chacha20Poly1305, "\x69\x6e\x64\x65\x70\x65\x6e\x64\x65\x6e\x74\x20\x4f\x70\x65\x6e\x53\x53\x4c\x20\x43\x68\x61\x43\x68\x61\x20\x6f\x72\x61\x63\x6c\x65\x20\x70\x6c\x61\x69\x6e\x74\x65\x78\x74", "\x62\x6f\x72\x72\x6f\x77\x65\x64\x20\x61\x61\x64", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b")
 check(ch.ok && mem.equal(ch.value.ciphertext, "\xe0\x95\x6c\x65\x59\x72\xcb\x24\xd2\xed\x4b\xd3\xd7\x6d\x6b\x0d\x9a\x23\xfe\xc7\x12\x1c\xcc\xfa\x8e\xf6\x0f\xaa\x07\xa1\xc5\x50\x89\xa0\x5c\x9f\x87\x77\xdf\xec\x52\x4a\x02") && mem.equal(ch.value.tag, "\x46\x3e\x13\xac\xd0\x49\xe9\xc3\x29\x84\x24\x9a\xe9\x49\xc1\x4e"))
 co := aead.open(&arena, aead.Cipher.Chacha20Poly1305, "\xe0\x95\x6c\x65\x59\x72\xcb\x24\xd2\xed\x4b\xd3\xd7\x6d\x6b\x0d\x9a\x23\xfe\xc7\x12\x1c\xcc\xfa\x8e\xf6\x0f\xaa\x07\xa1\xc5\x50\x89\xa0\x5c\x9f\x87\x77\xdf\xec\x52\x4a\x02", "\x46\x3e\x13\xac\xd0\x49\xe9\xc3\x29\x84\x24\x9a\xe9\x49\xc1\x4e", "\x62\x6f\x72\x72\x6f\x77\x65\x64\x20\x61\x61\x64", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b")
 check(co.ok && mem.equal(co.value, "\x69\x6e\x64\x65\x70\x65\x6e\x64\x65\x6e\x74\x20\x4f\x70\x65\x6e\x53\x53\x4c\x20\x43\x68\x61\x43\x68\x61\x20\x6f\x72\x61\x63\x6c\x65\x20\x70\x6c\x61\x69\x6e\x74\x65\x78\x74"))
 mark = mem.arena_mark(&arena)
 ch.value.tag[0] ^= 1
 cb := aead.open(&arena, aead.Cipher.Chacha20Poly1305, "\xe0\x95\x6c\x65\x59\x72\xcb\x24\xd2\xed\x4b\xd3\xd7\x6d\x6b\x0d\x9a\x23\xfe\xc7\x12\x1c\xcc\xfa\x8e\xf6\x0f\xaa\x07\xa1\xc5\x50\x89\xa0\x5c\x9f\x87\x77\xdf\xec\x52\x4a\x02", ch.value.tag, "\x62\x6f\x72\x72\x6f\x77\x65\x64\x20\x61\x61\x64", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b")
 check(!cb.ok && cb.kind == errors.Kind.InvalidInput && cb.provider_code == 0 && #len(cb.value) == 0 && mem.arena_used(&arena) == mark)
 for i in mark..mark + #len("\x69\x6e\x64\x65\x70\x65\x6e\x64\x65\x6e\x74\x20\x4f\x70\x65\x6e\x53\x53\x4c\x20\x43\x68\x61\x43\x68\x61\x20\x6f\x72\x61\x63\x6c\x65\x20\x70\x6c\x61\x69\x6e\x74\x65\x78\x74") { check(backing[i] == 0) }
 for k in 0..2 {
  kind := aead.Cipher.Aes256Gcm
  if k == 1 { kind = aead.Cipher.Chacha20Poly1305 }
  check(!aead.seal(&arena, kind, "x", "", "short", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b").ok)
  check(!aead.seal(&arena, kind, "x", "", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f", "").ok)
  check(!aead.open(&arena, kind, "x", "bad", "", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b").ok)
  huge := (&key[0])[..2147483648]
  check(!aead.seal(&arena, kind, huge, "", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b").ok)
  check(!aead.seal(&arena, kind, "", huge, "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b").ok)
  check(!aead.seal(&arena, kind, "", "", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f", huge).ok)
 }
 invalid_kind := aead.Cipher.Aes256Gcm
 invalid_ptr := #cast(*u8, &invalid_kind)
 invalid_ptr.* = 99
 check(!aead.seal(&arena, invalid_kind, "", "", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b").ok)
 check(!aead.seal(&arena, aead.Cipher.Chacha20Poly1305, "", "", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f", "12345678901").ok)
 check(!aead.seal(&arena, aead.Cipher.Chacha20Poly1305, "", "", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f", "1234567890123").ok)
 check(mem.arena_used(&arena) == mark)
 long_nonce: [129]u8
 check(!aes.gcm_seal(&arena, "data", "", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f", long_nonce[..]).ok && mem.arena_used(&arena) == mark)
 // GCM retains its variable nonempty nonce support.
 nonstandard := aes.gcm_seal(&arena, "data", "", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f", "12345678")
 check(nonstandard.ok && aes.gcm_open(&arena, nonstandard.value.ciphertext, nonstandard.value.tag, "", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f", "12345678").ok)
 for algorithm in 0..2 {
 overlap_kind := aead.Cipher.Aes256Gcm
 if algorithm == 1 { overlap_kind = aead.Cipher.Chacha20Poly1305 }
 // Each borrowed input conflicts separately with the pending output.
 for which in 0..6 {
  storage: [128]u8
  mem.fill(storage[..], 42)
  local := mem.arena_from_buffer(storage[..])
  _ = mem.push_bytes_uninit(&local, 7)
  p: []const u8 = "hello"
  ad: []const u8 = "aad"
  ke: []const u8 = "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f"
  no: []const u8 = "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b"
  if which == 0 { p = storage[8..13] }
  if which == 1 { ad = storage[8..11] }
  if which == 2 { ke = storage[8..40] }
  if which == 3 { no = storage[8..20] }
  if which == 4 { p = storage[..8] }
  if which == 5 { p = storage[25..30] }
  failed := aead.seal(&local, overlap_kind, p, ad, ke, no)
  check(!failed.ok && failed.kind == errors.Kind.InvalidInput && failed.error == 0 && failed.provider_code == 0 && #len(failed.value.ciphertext) == 0 && #len(failed.value.tag) == 0 && mem.arena_used(&local) == 7)
  for byte in storage { check(byte == 42) }
 }
 for which in 0..5 {
  storage: [128]u8
  mem.fill(storage[..], 42)
  local := mem.arena_from_buffer(storage[..])
  _ = mem.push_bytes_uninit(&local, 7)
  ci: []const u8 = "\xce\xa7\x40\x3d\x4d\x60\x6b\x6e\x07\x4e\xc5\xd3\xba\xf3\x9d\x18"
  ta: []const u8 = "\xd0\xd1\xc8\xa7\x99\x99\x6b\xf0\x26\x5b\x98\xb5\xd4\x8a\xb9\x19"
  ad: []const u8 = ""
  ke: []const u8 = "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f"
  no: []const u8 = "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b"
  if which == 0 { ci = storage[8..24] }
  if which == 1 { ta = storage[8..24] }
  if which == 2 { ad = storage[8..11] }
  if which == 3 { ke = storage[8..40] }
  if which == 4 { no = storage[8..20] }
  failed := aead.open(&local, overlap_kind, ci, ta, ad, ke, no)
  check(!failed.ok && failed.kind == errors.Kind.InvalidInput && failed.error == 0 && failed.provider_code == 0 && #len(failed.value) == 0 && mem.arena_used(&local) == 7)
  for byte in storage { check(byte == 42) }
 }
 }
 mem.arena_release(&arena)
 lazy: mem.Arena
 check(aes.gcm_seal(&lazy, "lazy", "", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f", "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b").ok)
 mem.arena_release(&lazy)
}
'''

KEYS = r'''use "std/crypto/exchange" ex
use "std/crypto/signature" sig
use "std/bytes"
use "std/errors"
fn check(ok: bool) { if !ok { #panic("key contract") } }
fn filled(data: []const u8, value: u8) bool { for i in 0..#len(data) { if data[i] != value { return false } }
return true }
fn fill(data: []u8) { for i in 0..#len(data) { data[i] = 165 } }
fn main() {
  alice: [32]u8 = [119, 7, 109, 10, 115, 24, 165, 125, 60, 22, 193, 114, 81, 178, 102, 69, 223, 76, 47, 135, 235, 192, 153, 42, 177, 119, 251, 165, 29, 185, 44, 42]
  alice_public: [32]u8 = [133, 32, 240, 9, 137, 48, 167, 84, 116, 139, 125, 220, 180, 62, 247, 90, 13, 191, 58, 13, 38, 56, 26, 244, 235, 164, 169, 142, 170, 155, 78, 106]
  bob_public: [32]u8 = [222, 158, 219, 125, 123, 125, 193, 180, 211, 91, 97, 194, 236, 228, 53, 55, 63, 131, 67, 200, 91, 120, 103, 77, 173, 252, 126, 20, 111, 136, 43, 79]
  shared: [32]u8 = [74, 93, 157, 91, 164, 206, 45, 225, 114, 142, 59, 244, 128, 53, 15, 37, 224, 126, 33, 201, 71, 209, 158, 51, 118, 240, 155, 60, 30, 22, 23, 66]
  seed: [32]u8 = [157, 97, 177, 157, 239, 253, 90, 96, 186, 132, 74, 244, 146, 236, 44, 196, 68, 73, 197, 105, 123, 50, 105, 25, 112, 59, 172, 3, 28, 174, 127, 96]
  public: [32]u8 = [215, 90, 152, 1, 130, 177, 10, 183, 213, 75, 254, 211, 201, 100, 7, 58, 14, 225, 114, 243, 218, 166, 35, 37, 175, 2, 26, 104, 247, 7, 81, 26]
  signature: [64]u8 = [229, 86, 67, 0, 195, 96, 172, 114, 144, 134, 226, 204, 128, 110, 130, 138, 132, 135, 127, 30, 184, 229, 217, 116, 216, 115, 224, 101, 34, 73, 1, 85, 95, 184, 130, 21, 144, 163, 59, 172, 198, 30, 57, 112, 28, 249, 180, 107, 210, 91, 245, 240, 89, 91, 190, 36, 101, 81, 65, 67, 142, 122, 16, 11]
  output: [96]u8 = []
  zero: [32]u8 = []
  zex := ex.Result{}
  zsig := sig.Result{}
  check(!zex.ok && #len(zex.value) == 0 && zex.kind == errors.Kind.None && zex.error == 0 && zex.provider_code == 0)
  check(!zsig.ok && #len(zsig.value) == 0 && zsig.kind == errors.Kind.None && zsig.error == 0 && zsig.provider_code == 0)
  fill(output[..])
  if true { r := ex.x25519_public(output[..], alice[..])
    check(r.ok && r.kind == errors.Kind.None && r.error == 0 && r.provider_code == 0)
    check(#len(r.value) == 32 && bytes.equal(r.value, alice_public[..]) && filled(output[32..], 165))
    check(&r.value[0] == &output[0])
    r.value[0] = 19
    check(output[0] == 19)
  }
  fill(output[..])
  if true { r := ex.x25519(output[..], alice[..], bob_public[..])
    check(r.ok && r.kind == errors.Kind.None && r.error == 0 && r.provider_code == 0)
    check(#len(r.value) == 32 && bytes.equal(r.value, shared[..]) && filled(output[32..], 165))
    check(&r.value[0] == &output[0])
    r.value[0] = 19
    check(output[0] == 19)
  }
  fill(output[..])
  if true { r := sig.ed25519_public(output[..], seed[..])
    check(r.ok && r.kind == errors.Kind.None && r.error == 0 && r.provider_code == 0)
    check(#len(r.value) == 32 && bytes.equal(r.value, public[..]) && filled(output[32..], 165))
    check(&r.value[0] == &output[0])
    r.value[0] = 19
    check(output[0] == 19)
  }
  fill(output[..])
  if true { r := sig.ed25519_sign(output[..], "", seed[..])
    check(r.ok && r.kind == errors.Kind.None && r.error == 0 && r.provider_code == 0)
    check(#len(r.value) == 64 && bytes.equal(r.value, signature[..]) && filled(output[64..], 165))
    check(&r.value[0] == &output[0])
    r.value[0] = 19
    check(output[0] == 19)
  }
  check(sig.ed25519_verify(signature[..], "", public[..]))
  check(!sig.ed25519_verify(signature[..], "x", public[..]))
  check(!sig.ed25519_verify(signature[..63], "", public[..]))
  fill(output[..])
  if true { r := ex.x25519_public(output[..31], alice[..])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := ex.x25519_public(output[..], alice[..31])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := ex.x25519(output[..31], alice[..], bob_public[..])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := ex.x25519(output[..], alice[..31], bob_public[..])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := ex.x25519(output[..], alice[..], bob_public[..31])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := sig.ed25519_public(output[..31], seed[..])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := sig.ed25519_public(output[..], seed[..31])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := sig.ed25519_sign(output[..63], "", seed[..])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := sig.ed25519_sign(output[..], "", seed[..31])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := ex.x25519_public(output[..], output[..32])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := ex.x25519_public(output[..], output[64..96])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := ex.x25519(output[..], alice[..], output[32..64])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := ex.x25519(output[..], output[16..48], bob_public[..])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := sig.ed25519_public(output[..], output[64..96])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := sig.ed25519_sign(output[..], "", output[..32])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := sig.ed25519_sign(output[..], output[80..96], seed[..])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  if true { r := sig.ed25519_sign(output[..], output[..1], seed[..])
    check(!r.ok && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.provider_code == 0 && #len(r.value) == 0)
    check(filled(output[..], 165))
  }
  fill(output[..])
  failed := ex.x25519(output[..], alice[..], zero[..])
  check(!failed.ok && failed.kind == errors.Kind.System && failed.error == 0 && #len(failed.value) == 0)
  check(failed.provider_code == 0)
  check(filled(output[..32], 0) && filled(output[32..], 165))
  check(bytes.equal(alice[..], alice[..]) && filled(zero[..], 0))
}
'''


def run(project, release, panic=False):
    output = project / ("program.exe" if os.name == "nt" else "program")
    subprocess.run([DYN, "build", str(project), "--no-cache", "--quiet",
                    "--output", str(output)] + (["--release"] if release else []),
                   check=True, timeout=90)
    result = subprocess.run([str(output)], capture_output=True, text=True, timeout=15)
    if panic:
        assert result.returncode != 0 and "arena exhausted" in result.stderr, result
    elif result.returncode:
        raise AssertionError(f"{project.name}: {result.stdout}\n{result.stderr}")


def project(root, name, source):
    path = root / name
    path.mkdir()
    (path / "main.dyn").write_text(source, encoding="utf-8")
    return path


with tempfile.TemporaryDirectory(prefix="dyn-crypto-results-") as temporary:
    root = Path(temporary)
    cases = [project(root, "aead", AEAD), project(root, "keys", KEYS)]
    exhaustion = []
    for cipher in ("Aes256Gcm", "Chacha20Poly1305"):
        for operation in ("seal", "open"):
            arguments = '"hello", "", key[..], nonce[..]'
            if operation == "open":
                arguments = '"hello", tag[..], "", key[..], nonce[..]'
            source = ('use "std/mem" mem\nuse "std/crypto/aead" aead\n'
                      'fn main() {\n backing: [4]u8\n'
                      ' arena := mem.arena_from_buffer(backing[..])\n'
                      ' key: [32]u8\n nonce: [12]u8\n tag: [16]u8\n'
                      f' _ = aead.{operation}(&arena, aead.Cipher.{cipher}, {arguments})\n}}\n')
            exhaustion.append(project(root, cipher + "-" + operation, source))
    for release in (False, True):
        for case in cases:
            run(case, release)
        for case in exhaustion:
            run(case, release, panic=True)
        print("PASS crypto results " + ("release" if release else "debug"), flush=True)

    # Both AEADs now compile and execute without the Linux OpenSSL provider.
    for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows','wasm32-wasi'):
        output = root / target
        subprocess.run([DYN,'build',str(cases[0]),'--target',target,'--release','--quiet','--output',str(output)],check=True,timeout=300)
        emulator = {'aarch64-linux':'qemu-aarch64','riscv64-linux':'qemu-riscv64','x86_64-windows':'wine'}.get(target)
        if emulator and shutil.which(emulator): subprocess.run([emulator,str(output)],check=True,timeout=60)
        if target == 'wasm32-wasi' and shutil.which('node'):
            script = "const {WASI}=require('node:wasi'),fs=require('fs');(async()=>{const wasi=new WASI({version:'preview1',returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});"
            subprocess.run(['node','--no-warnings','-e',script,str(output)],check=True,timeout=60)
    print('PASS native AEAD facade cross-targets')
