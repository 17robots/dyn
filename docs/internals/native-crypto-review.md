# Native crypto review record

Review date: 2026-10-26. This records source review and a bounded inspection of
emitted code, not a security certification. Functional tests and source inspection
support the arithmetic and API claims below. They do not establish constant-time
execution on every processor, operating system, compiler version or backend.

The source review covered every function in `std/crypto`, including the complete
private-operation paths and the small public wrappers. The relevant transitive
paths in `std/encoding/binary`, `std/bytes`, SHA256/HMAC, memory arenas and Linux
syscall-number translation were also inspected. X509 is an explicit ordered-chain
profile, separate from the TLS provider. Review outcomes for malformed X509 names,
SANs and leaf public keys were supplied to its implementation owner.

## Threat model and terminology

Keys, expanded keys, scalar bits, derived nonces, MAC states and unauthenticated
plaintext are secret. Message lengths, addresses, output capacities, algorithm
selection, nonces and iteration counts are treated as public. Message contents
may be secret in encryption, hashing, signing and password derivation. Signature
verification inputs and certificate contents are public.

“Fixed schedule” here means content does not choose source-level loop counts,
branches or memory indexes in the arithmetic core, for valid API states and equal
public lengths. It does not mean no conditional branch instructions are emitted.
The compiler retains pointer/alignment/bounds and checked-arithmetic guards.
A guard evaluated using a secret intermediate is harmless only if its outcome is
invariant over all valid intermediate values; the bounds below are part of that
argument. Public state fields must not be corrupted by callers. Arbitrary manual
`Field`/`State` values are outside these arithmetic invariants.

P256 RFC6979 rejection sampling is a stated exception: rejecting an out-of-range
nonce or zero r/s can change signing runtime. The private scalar multiplication
itself has a fixed schedule. Thus this record does **not** claim that the complete
P256 signing API has identical control flow for every private key and digest.

## Arithmetic and source control flow

### AES256-GCM and the arena AEAD facade

`std/crypto/aesgcm` uses an eight-iteration GF(2^8) multiply and a fixed addition
chain for x^254, followed by the AES affine transform. Reduction uses masks,
including for zero; there is no secret-indexed S-box. AES256 expands 60 words,
uses 14 rounds, and omits MixColumns in round14. Key-schedule and round branches
use public indexes. Byte shifts that intentionally discard high bits use `#wrap`.

GHASH performs 128 bit steps. The high/low selection branch uses the public loop
index; secret bits choose masks, not branches or addresses. Authentication hashes
separately padded AAD and ciphertext, then their big-endian bit lengths. A 12-byte
nonce uses nonce||1; other supported nonces use the GHASH nonce construction.
`inc32` wraps the low32 counter bits intentionally. The payload cap is
(2^32-2)*16 = 68719476704 bytes; AAD is limited to 2^61-1 bytes so its bit count
fits u64. The nonce compatibility profile is 1..128 bytes, not all possible GCM
IV lengths.

Low-level `open` compares the complete tag before decrypting. Exact payload
in-place use is allowed; partial overlap and other mutable-output/input overlaps
are rejected before writes. Failure preserves the low-level destination. The
arena facade retains its existing INT_MAX payload/AAD bounds, validates pending
allocations against all borrowed inputs, allocates before authentication, and
zeroes then rewinds on rejection. It returns no partial plaintext. Arena exhaustion
continues to panic. `error` and compatibility `provider_code` remain zero.

### ChaCha20, Poly1305 and their AEAD composition

ChaCha20 additions widen two u32 values to u64 (sum<2^33). Rotations use fixed
7/8/12/16 amounts; the largest widened product is below2^48. Reduction modulo2^32
and rotations do not index secret tables. There are ten fixed double rounds.
The counter ceiling uses quotient plus remainder, avoiding `len+63` overflow.
The raw XOR API permits exact in-place payload operation; it does not reject
partial overlap or destination overlap with key/nonce. Such raw overlaps are not
qualified safe. The AEAD composition rejects these overlaps itself.

Poly1305 uses the RFC8439 clamped r masks and five radix-2^26 limbs. Let B=2^26.
A conservative induction bounds pre-multiply h limbs by3B and r limbs belowB.
Each convolution is below75B²; carry additions stay below2^59, safely insideu64.
After propagation/folding, h0/h2..4 are normalized and h1<B+376. The final carry
pass, wrapped subtraction of2^130-5, and high-bit-derived mask select the canonical
residue without a secret-dependent reduction branch. Masked32-bit words precede
pad addition, so serialization does not double-count limb carries. A partial
message appends byte1 then zeroes the rest; complete blocks supply the implicit
2^128 bit. Finishing clears and consumes the state. Tag comparison reads all 16
bytes and OR-reduces XOR differences; public length mismatch can return early.

ChaCha20-Poly1305 obtains its one-time MAC key from the first32 bytes of counter0
and encrypts from counter1. It MACs AAD, pad16, ciphertext, pad16 and two LE64 byte
lengths. Its payload cap permits at most2^32-1 blocks. Authentication precedes
plaintext writes. Caller nonce uniqueness and one-time Poly1305-key use remain
protocol requirements, not properties the library can infer.

### Curve25519, X25519 and Ed25519

The field is sixteen signed radix-2^16 limbs with fixed-index convolution,
carry propagation, two masked canonical subtractions and fixed public exponent
schedules. Signed right shift must implement arithmetic shift for negative carries;
this was checked in the selected emitted targets.

For the actual curve call graph, multiply operands have absolute limbs below4B,
B=65536: normalized outputs are combined by at most one add/subtract before the
next multiply; public constants also fit this bound. An interval calculation
bounds the folded convolution by39238821216256 (<2^46). Two carry passes give
limb0 in[-38,65573] and other limbs in[0,65535], closing the invariant. Intermediate
carry additions, products by38/65536, and pack subtraction are far insidei64.
This is a bound for internal curve operations, not a general guarantee for
arbitrary user-created `curve25519.Field` limbs.

X25519 clamps a copied scalar, masks the input-coordinate top bit, performs255
fixed ladder steps with XOR/AND swaps, inverts with a public exponent, and rejects
an all-zero result using a complete32-byte OR reduction. The exchange facade
rejects destination-tail aliases and clears only the32-byte result prefix on
arithmetic rejection. Low-level shared copies/decodes both inputs before output.

Ed25519 uses complete extended-coordinate additions and256 swap/add/double steps,
with no secret scalar-bit branch or precomputed secret-indexed table. Scalar
reduction follows the fixed TweetNaCl schedule. Input hash bytes are0..255;
signature accumulation has at most32 products255*255 plus one byte per limb.
An interval pass through reduction bounds its signed intermediates below2^34,
including conservative carry products. Checked i64 arithmetic therefore does not
need a data-dependent exceptional path for valid internal values.

Ed25519 verification is intentionally variable-time on public inputs: S<L,
canonical point encodings, nonidentity prime-subgroup public keys, square-root
checks, public-point parity correction and final encoded-point equality can
branch. Public-key validation uses that same factored path. This stricter public
key acceptance is not a promise to accept every encoding tolerated by OpenSSL or
older TweetNaCl. Signing/public derivation use the fixed-schedule path instead.

### P256 and deterministic ECDSA

Eight u32 limbs represent canonical residues. Per-limb additions are at most
2^33-1. Subtraction uses 2^32+a-b-borrow in[0,2^33-1], deriving borrow arithmetically.
Conditional modular correction uses masks. Because each operand is below the
modulus, one correction is sufficient; conversion of a256-bit hash/coordinate
also needs at most one subtraction for these moduli, both greater than2^255.

Modular multiply runs256 double/add/select steps. Inversion uses fixed exponent
p-2 or n-2; its exponent branches depend only on the chosen public modulus.
Jacobian addition computes generic and doubling candidates and mask-selects
same-point/identity exceptions. Opposite points retain z=0. Scalar multiplication
always doubles, adds and mask-selects for256 bits. Conversion to affine uses the
same fixed exponent inversion. There is no general big-integer division or
secret-indexed table in this path.

Public keys require uncompressed SEC1 length65, canonical x/y and the curve
equation; cofactor1 makes the on-curve test sufficient for subgroup membership.
Verification requires raw64-byte r||s with1<=r,s<n and rejects an infinity sum.
These checks and verification comparisons operate on public values and may branch.

RFC6979 uses HMAC-SHA256 and reduced hash octets. It retries invalid nonce
candidates or zero signature components, up to128 attempts; output is written only
on success. Returned signatures are not low-S normalized. Invalid private scalars
are rejected, and validation preserves caller output. The high-level signature
facade preserves result-prefix/tail ownership and rejects full-destination aliases.
This is a portable reference implementation, not a throughput claim.

### SHA256, SHA512, HMAC and derivation

SHA256/SHA512 round counts, message schedules and constant indexes depend only
on public block numbers. Choice/majority and rotations do not branch on content.
SHA256's widened add/shift helpers stay withinu64, then reduce modulo2^32.
SHA512 uses wrapped u64 round arithmetic. SHA256 limits total bytes to2^61-1 and tests remaining block length by
subtraction, including on 32-bit targets;
SHA512 maintains a125-bit byte count for its128-bit final bit length. Streaming
buffer branches reveal public chunk lengths only. SHA512 consumes its state on
finish; SHA256's older finish API must not be assumed to have the same lifecycle.

HMAC copies or hashes the key before output, computes both inner/outer digests
in fixed-size temporary storage and uses the fixed SHA256 core. Destination
aliasing with HMAC's key/message is safe because output occurs after their last
read. HKDF permits at most255 SHA256 blocks; PBKDF2 permits at most2^32-1 blocks
and requires positive iteration count. Their loop counts and block-index increments
are public; password bytes do not select memory indexes or early exits. Scratch
space and borrowed input/output overlap require explicit validation because
multiple HMAC invocations reread their borrowed inputs.

Audit findings and their final disposition are recorded below rather than hidden
by vector success.

## Entropy and parsing seams

Linux randomness retries EINTR and partial reads; syscall318 is translated to278
for Linux AArch64/RISC-V by `src/target.c`. Darwin uses getentropy chunks<=256;
Windows checks the signed native status and chunks the ULONG request length.
Failure returns false, potentially after filling a prefix; callers must discard
that output. There is no deterministic fallback. The WASM backend deliberately
rejects nonempty requests. Native OS entropy quality and failure injection were
not established by the arithmetic vector tests.

DER validates TLV length bounds by subtraction, rejects indefinite/nonminimal
length forms and overflow, and makes failure sticky. Returned elements borrow
input. It is a low-tag-number TLV reader, not a complete schema-independent DER
validator: integer/boolean/bit-string and constructed-content semantics belong to
its caller. The certificate envelope parser checks its outer three fields and
signature unused-bit byte; `x509.inspect` supplies the deeper certificate profile.
The reviewed X509 fixes validate every supported leaf/issuer public key, validate
UTF8/Printable/IA5/BMP/Universal name strings, validate directoryName SAN contents,
and reject unsupported constructed GeneralName forms. Its exact-name matching,
explicit anchors/time, supported algorithms and omitted revocation/discovery
remain deliberate profile limits, not browser trust-store equivalence.

PEM owns decoded bytes but borrows its label. Failure rewinds the arena and
publishes no payload. Rewind is not a secure erasure guarantee. PEM allocates
input-sized scratch before finding the first block; callers must bound untrusted
input and provide appropriate arena capacity. Label grammar/tolerated whitespace
are a PEM profile, not a universal canonicalization claim. DER/PEM/X509 branches
operate on public encodings and have no constant-time requirement here.

## Emitted-code inspection

The inspection used `build/dyn-release` on Linux x86-64, AMD Ryzen9 9950X, with
LLVM objdump23.1.4. Six objects were generated: x86_64-linux, aarch64-linux and
riscv64-linux, each release O2 and O3. The latter two were disassembled, not
executed on physical ARM/RISC-V hardware during this instruction review.

At all six selected sites, AES GF multiply/GHASH secret bits remained arithmetic
masks; Poly1305 final reduction remained shift/subtract/AND/OR selection;
Curve25519 swap remained XOR/AND; P256 selection remained AND/OR; and complete
MAC comparison loops had no byte-mismatch exit. x86 used `sete`, AArch64 `cset`,
and RISC-V arithmetic zero-test for comparison results. Loop exits, public length
checks, address checks, aggregate moves and checked-overflow guards remain.
Curve carry/reduction shifts were arithmetic SAR/ASR/SRA. No div/idiv/udiv/sdiv or
RISC-V div/rem instructions were found in the six complete driver objects after
all required disassembler ISA features were enabled; this is an observation about
these objects, not a compiler-wide rule.

The inspection was focused on masks, reduction, comparison and representative
checked arithmetic. It was not a complete instruction-by-instruction secret-taint
proof of every caller or optimizer transformation. It does not measure cache,
speculation, multiplier latency, power/EM, contention, faults, or timing statistics.
It excludes physical-target instruction latency qualification, 32-bit curve code,
WASM engine optimization, alternate CPU tuning and future compiler revisions.
Stack key material is not comprehensively guaranteed erased; source zeroing must
not be mistaken for verified elimination of every spill or compiler copy.

## Reproduce the instruction artifacts

From the compiler root, create a temporary directory containing this `main.dyn`.
The public wrappers keep the reviewed call paths externally callable and prevent
a constant-only main from being the sole emitted evidence.

```dyn
use "std/crypto/aesgcm" aes
use "std/crypto/chacha20" chacha
use "std/crypto/poly1305" poly
use "std/crypto/curve25519" field
use "std/crypto/x25519" x
use "std/crypto/ed25519" ed
use "std/crypto/p256" p
use "std/crypto/sha512" sha
pub fn aes_seal(o: []u8,t: []u8,m: []const u8,a: []const u8,k: []const u8,n: []const u8) bool { return aes.seal(o,t,m,a,k,n) }
pub fn aes_open(o: []u8,m: []const u8,t: []const u8,a: []const u8,k: []const u8,n: []const u8) bool { return aes.open(o,m,t,a,k,n) }
pub fn chacha_block(o: []u8,k: []const u8,n: []const u8,c: u32) bool { return chacha.block(o,k,n,c) }
pub fn chacha_xor(o: []u8,m: []const u8,k: []const u8,n: []const u8,c: u32) bool { return chacha.xor(o,m,k,n,c) }
pub fn poly_finish(s: *poly.State) poly.Tag { return poly.finish(s) }
pub fn poly_equal(a: []const u8,b: []const u8) bool { return poly.equal(a,b) }
pub fn field_swap(a: *field.Field,b: *field.Field,bit: i64) { field.select(a,b,bit) }
pub fn field_mul(a: field.Field,b: field.Field) field.Field { return field.multiply(a,b) }
pub fn x_shared(o: []u8,k: []const u8,pub: []const u8) bool { return x.shared(o,k,pub) }
pub fn ed_sign(o: []u8,m: []const u8,k: []const u8) bool { return ed.sign(o,m,k) }
pub fn p_sign(o: []u8,m: []const u8,k: []const u8) bool { return p.sign(o,m,k) }
pub fn sha_update(s: *sha.State,m: []const u8) bool { return sha.update(s,m) }
fn main() {}
```

Build each combination, substituting the actual temporary directory:

```sh
build/dyn-release build /tmp/dyn-crypto-audit --release --target x86_64-linux --opt-level 2 --emit-asm --no-link --no-cache --quiet --output /tmp/dyn-crypto-audit/x86_64-linux-o2
llvm-objdump -d /tmp/dyn-crypto-audit/x86_64-linux-o2.o > /tmp/dyn-crypto-audit/x86_64-linux-o2.dump
```

Repeat with O3 and `aarch64-linux`/`riscv64-linux`. For RISC-V use
`llvm-objdump --mattr=+m,+a,+f,+d -d`; otherwise valid multiply/ABI instructions
can display as unknown. Find module-qualified `multiply`, `product`, `finish`,
`equal_constant_time`, `equal`, `select`, `choose`, `zero_bit`, `carry`, `modulo`
and scalar routines in the resulting dump, keeping identically named modules
separate. Generated symbol hashes and offsets are artifact identifiers, not APIs.

## Functional evidence and boundaries

Reviewer-run gates passed on the reviewed implementation:

```sh
python3 tests/poly1305-results.py
python3 tests/chachapoly-results.py
python3 tests/aesgcm-results.py
python3 tests/curve25519-results.py
python3 tests/p256-results.py
python3 tests/crypto-results.py
python3 tests/kdf-results.py
python3 tools/std-lint.py
```

They cover RFC8439/RFC7748/RFC8032/RFC6979 and NIST answers, independent Python
integer/hashlib or saved OpenSSL oracle values, streaming splits, boundary scalar
values, crafted P256 equal/opposite final point additions, tampering, aliases,
result-prefix/tail preservation, arena failure cleanup, and cross compilation.
Host debug/O2/O3 and available QEMU AArch64/RISC-V, Wine x86-64 and Node WASI
executions passed. MacOS and Windows AArch64 artifacts were cross-built, not
executed. These are finite examples, not exhaustive cryptanalysis or a replacement
for an independent security review of newly written curve implementations.

A separate temporary raw-ChaCha regression used a forged slice of length
`~#cast(usize,0)` with counter4294967295. It returned false before access, leaving
the actual32-byte backing unchanged, on host64, QEMU AArch64/RISC-V and Node
WASM32 in debug/release. This specifically exercises the ceiling division and
counter bound without allocating or reading the forged payload:

```dyn
use "std/crypto/chacha20" chacha
fn main() {
  key: [32]u8
  nonce: [12]u8
  forged := (&key[0])[..~#cast(usize, 0)]
  if chacha.xor(forged, forged, key[..], nonce[..], 4294967295) { #panic("counter") }
  for byte in key { if byte != 0 { #panic("storage") } }
}
```

## Findings disposition

Resolved during this review:

- HMAC's long-key path now propagates a failed SHA256 key hash instead of
  silently using the zero key. Oversized-key failure leaves destination unchanged.
- HKDF/PBKDF2 validate scratch-size additions using subtraction first. Their SHA256
  length allowances include the64-byte HMAC inner pad: HKDF info<=limit-97
  (32 previous bytes+1 counter+64 pad), PBKDF2 salt<=limit-68 (4 counter+64 pad).
- Both reject scratch/destination overlap with each other and with borrowed
  repeatedly read inputs, including unused provided tails, before writing.
- SHA256's remaining-block test uses `len-at>=64`, avoiding a near-usizeMax
  addition on 32-bit targets.

The original temporary two-block derivation reproducer returned true with
incorrect bytes when destination overlapped the borrowed key/password. Rebuilt
against the fixes it returns false; the oversized HMAC reproducer now returns an
empty slice. `tests/kdf-results.py` passes independent HMAC/HKDF/PBKDF2 vectors,
storage-preserving aliases, forged size guards and the raw-ChaCha counter proof
on the recorded host/cross/emulated matrix. The selected emitted sites were
regenerated after these fixes; instruction bodies remained unchanged after
normalizing relocation addresses and AArch64 page-symbol annotations.

Remaining review limits include raw ChaCha partial-overlap misuse, corrupted
public arithmetic states, PEM profile/capacity behavior, and runtime/key-material
zeroization. No security certification is implied by resolving the concrete
findings or passing the finite vector gates.

## Reviewed-source and artifact fingerprints

The SHA256 digests below identify exact reviewed file content. Working-copy
commit IDs change while other agents integrate unrelated work; per-file digests
are the source identity for this record. Re-run the audit when the compiler,
primitives, helper arithmetic, backend or relevant optimization changes.

Source freeze: parent-reported crypto-fix commit `3555a2e6`; the per-file
digests also cover reviewed source in the shared working tree. Compiler binary
SHA256: `b281ea7e64900dcf4bd306ec6240193cc5025f82c474dce3bc5f3e49ba245618`.

```text
b2f812e1342805389874570422674b686771ec6c8cdc9ee3e2007cadba4d5121  std/crypto/aead/aead.dyn
eb260550a464a5d49f4b9c71ce16a07184b03d75b33799a760124c65420aa945  std/crypto/aes/aes.dyn
b1abff21042bc95db6b28a37c9fbce7de62ef64a5298e0310126cd4aa817e06e  std/crypto/aesgcm/aesgcm.dyn
8eb4894708f541e346d6b6ffbeeffb0339fa69b8cf714c16dbad294eaa68e9a2  std/crypto/certificate/certificate.dyn
bbec69263e152348dc771be5080510b645c613b0b99001a8c2bb1f4337d69c51  std/crypto/chacha20/chacha20.dyn
d34b243abf7ffcdbd66b299c4987dd3491c3cdb98420ea7910a6e898eefed318  std/crypto/chacha20poly1305/chacha20poly1305.dyn
4c824db956866db2f25a4f92be474cee0933702565e8833b30aba0f04175c9c8  std/crypto/core/core.dyn
abddb787b6b6ab2c1f338f5a604f6246ea01b1578c08a95f5df052fd2a6bdfdc  std/crypto/core/random_linux.dyn
bc4441bed10bbc99eb4bc07996385c044a0344631a8b4668904a6a8c56b7d64a  std/crypto/core/random_macos.dyn
6d19274b54b1169792cf8519d8ff1cdfa3b50377b4bd0fa1e58f47611974e8cf  std/crypto/core/random_wasm.dyn
6c3eaaa885f9395209ca588a2be3af65a010c2b55b7de29c3420373f3d877dd2  std/crypto/core/random_windows.dyn
28db678fc43319d22da4dfc430b365a46243601a0074f29d30f8f0ea53690405  std/crypto/curve25519/curve25519.dyn
4c3613499fe98530d2d4938c1a4e7ca281b8489f25230212852a1b9c09f38b49  std/crypto/der/der.dyn
542493c828d91891eec51edfeba9bdf12d5d5fdbbbc5a967729709cecb1e7dbf  std/crypto/ed25519/ed25519.dyn
6d903af00a950dc2dcaaf93980a6bbffd87ecf370114bdc2ee419e6f7a86a659  std/crypto/exchange/exchange.dyn
0f35d1328bc37c2d23233154da92bf092a67211cceba04cd95bbd546b8bdf40b  std/crypto/hmac/hmac.dyn
7ec26372fb4f924a51d6c8f186cff8cd4ba2b1dc163426e0cd6e8ae7d811e994  std/crypto/kdf/kdf.dyn
bb5ebb09cc5d78e774c4169609991f5e55442f2b15cf651d36c2837c5b369f51  std/crypto/p256/p256.dyn
d2c564c28597a8f9a16a18710a39aba079f1b1dfda09d253f51090b6cabc4492  std/crypto/password/password.dyn
f190b004ffa0e4918f29a8a93889b5844f7e45399cb66ed3bb9f7a320c9d7fc5  std/crypto/pem/pem.dyn
5826a01c2df33d68880e0d05bd006d6e56947e096d201cc0272967c189c1950d  std/crypto/poly1305/poly1305.dyn
b7d888d5d4d78def2e62de1cefcc14ce2d73f2bd0dc95170a2272435d72a5db2  std/crypto/random/random.dyn
fe951980ece0f433e2615f467ed563c45051d7c54bab5b1b74a89355fa004f8f  std/crypto/sha2/sha2.dyn
a03049fd6e06bee639227442a99bb7e073f788edb83cb8dfbc75a105d81b4e43  std/crypto/sha512/sha512.dyn
f1602bc7b8e0fa27d56e9a5d19a5e7df07b05bb1afeb836f312ad231989f5f45  std/crypto/signature/signature.dyn
4077ea84ac87fe827263755338075959da18c6d013244a4287400243ce4cefb7  std/crypto/x25519/x25519.dyn
869daafb400789ae13e0d577a1c337748a011363ff3d2cf8f14ec2aec9d9ea9b  std/crypto/x509/x509.dyn
165ce486c4e8d49e08630dd96339ed8e000248ac6f5e723857af860dfd7e78da  std/encoding/binary/binary.dyn
81d3048b40504bf8fc693558af1804e98accc5fde51c67ef2f990b421616f88a  std/bytes/bytes.dyn
9910db9c73a4069319a14a7681a4f557854e7e86952d5cfe8aa168e251cebafb  std/mem/mem.dyn
be7e263b3532d261016af26ebc5a7ab7905a2ac6bcfa3e4c987996b1a47a6aed  src/target.c
```

Emission-driver SHA256: `1d7dcff5a464c733831e3bd0e65be3fa89880b0c72d72e1117eb808f943074e0`.

| Target | Optimization | Object SHA256 |
|---|---|---|
| x86_64-linux | O2 | `8a86316662e176b0bdd35527a002f1a0623b9541f9cb73c5797aac11d8f9543e` |
| x86_64-linux | O3 | `4a16c2718f442455c49a4be0d6fa32598dc3f5c9d207453cb065ceafc5e7707a` |
| aarch64-linux | O2 | `2201d85e551668c05312e89d6e4fbcd22384ea4c9efccd138622b0168a16afdf` |
| aarch64-linux | O3 | `7307a5a18abf6d22ad686cefbfdb4856d73cc192c665a62f4db88c993f1d50fd` |
| riscv64-linux | O2 | `5470e5ee3a1d7d9eb18f4ff5801894edf9b905799f36b2be56ca4bc866ee505f` |
| riscv64-linux | O3 | `3e1a8fc342c785a1a2da416aa483431e64b30fc506c56a27d0d13c2a637e373a` |

These hashes identify this review run. Exact reproduction additionally depends
on the compiler build and embedded runtime; they are not stable ABI fingerprints.
