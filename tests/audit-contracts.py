#!/usr/bin/env python3
"""Compiler/runtime/SDK audit regressions, exercised in debug and release."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/repository-audit'
OUT.mkdir(parents=True, exist_ok=True)
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve()
CASES = {
'url-relative-colon': '''use "std/net/url"
use "std/bytes"
fn main() { parsed := url.parse("path/to:file")
 if !parsed.ok || #len(parsed.value.scheme) != 0 || !bytes.equal(parsed.value.path, "path/to:file") { #panic("relative path misparsed as scheme") } }
''',
'path-dot-root': '''use "std/path"
fn main() { output: [64]u8 = []
 if !path.safe_join(output[..], ".", "file").ok { #panic("safe_join rejects current directory") } }
''',
'pem-final-line': '''use "std/crypto/pem"
fn main() { output: [32]u8 = [] scratch: [64]u8 = []
 if !pem.decode(output[..], "-----BEGIN TEST-----\\nYQ==\\n-----END TEST-----", scratch[..]).ok { #panic("PEM END at EOF rejected") } }
''',
'slot-map-reinit': '''use "std/container/slot_map" slots
fn main() { data: [1]u8 = [] generations: [1]u32 = [] occupied: [1]u64 = []
 state := slots.init(data[..], generations[..], occupied[..], 1)
 old := slots.insert(&state, "a")
 state = slots.init(data[..], generations[..], occupied[..], 1)
 _ = slots.insert(&state, "b")
 if slots.get(&state, old).ok { #panic("old handle revived after reinit") } }
''',
'zip-empty': '''use "std/archive/zip"
fn main() { archive: [22]u8 = [80,75,5,6,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
 state := zip.open(archive[..])
 if zip.next(&state).error != zip.ErrorKind.End { #panic("empty ZIP rejected") } }
''',
'fs-self-copy': '''use "std/fs"
fn main() { scratch: [64]u8 = []
 if !fs.write_all("build/repository-audit/copy-fixture", "keep me").ok { #panic("setup") }
 result := fs.copy_file("build/repository-audit/copy-fixture", "build/repository-audit/copy-fixture", scratch[..])
 if result.ok || fs.metadata("build/repository-audit/copy-fixture").size != 7 { #panic("self-copy destroys source") } }
''',
'fs-nul-path': '''use "std/fs"
fn main() {
 if !fs.write_all("build/repository-audit/nul-fixture", "keep").ok { #panic("setup") }
 result := fs.write_all("build/repository-audit/nul-fixture\\0ignored", "oops")
 if result.ok { #panic("embedded NUL path silently accepted") } }
''',
'comment-import-member': '''use "std/bytes"
fn main() { if !bytes./* comment */equal("a", "a") { #panic("equal") } }
''',
'comment-import-type': '''use "std/mem"
fn consume(value: *mem./* comment */Arena) { _ = value }
fn main() {}
''',
}
key = bytes(range(33))
expected = hmac.new(key, b'info\x01', hashlib.sha256).digest()
CASES['hkdf-long-prk'] = '''use "std/crypto/kdf"
use "std/bytes"
fn main() { key: [33]u8 = [%s] expected: [32]u8 = [%s]
 output: [32]u8 = [] scratch: [64]u8 = []
 if !kdf.hkdf_expand(output[..], key[..], "info", scratch[..]) || !bytes.equal(output[..], expected[..]) { #panic("HKDF key truncated") } }
''' % (','.join(map(str,key)), ','.join(map(str,expected)))

CASES.update({
'xml-invalid-attribute': '\n'.join(['use "std/encoding/xml"', 'fn main() { stack: [8][]const u8 = []', ' if xml.valid("<a broken/>" , stack[..]) { #panic("invalid XML attributes accepted") } }']),
'http-invalid-transfer': '\n'.join(['use "std/net/http"', 'fn main() { head := http.parse_request("POST / HTTP/1.1\\r\\nTransfer-Encoding: chunkedjunk\\r\\n\\r\\n")', ' if head.ok && head.chunked { #panic("invalid transfer coding accepted as chunked") } }']).replace('\\\\r', '\\r').replace('\\\\n', '\\n'),
'fs-read-proc': '\n'.join(['use "std/fs"', 'use "std/mem"', 'fn main() { storage: [65536]u8 = [] arena := mem.arena_from_buffer(storage[..])', ' result := fs.read_all(&arena, "/proc/version", 65536)', ' if !result.ok || #len(result.data) == 0 { #panic("read_all fails readable proc file") } }']),
})
# A minimal stream adapter permits deterministic packet/chunk tests without networking.
stream_support = '''
use "std/io"
struct Input { bytes: []const u8, at: usize }
fn read_input(raw: rawptr, destination: []u8) io.Result {
 state := #cast(*Input) raw
 count := #len(state.bytes) - state.at
 if count > #len(destination) { count = #len(destination) }
 i: usize = 0 for i < count { destination[i] = state.bytes[state.at + i] i += 1 }
 state.at += count
 if count == 0 { return io.Result{ status: io.Status.End } }
 return io.Result{ transferred: count }
}
fn write_output(raw: rawptr, source: []const u8) io.Result { _ = raw return io.Result{ transferred: #len(source) } }
'''
CASES['zip-repeat-end'] = stream_support + '\n'.join([
 'use "std/archive/zip"',
 'fn main() { input := Input{ bytes: "" } header: [30]u8 = [] name: [1]u8 = [] payload: [1]u8 = []',
 ' state := zip.stream_reader(io.Reader{ data: #cast(rawptr) &input, read: &read_input }, header[..], name[..], payload[..])',
 ' if zip.next_stream(&state).error != zip.ErrorKind.End { #panic("setup") }',
 ' if zip.next_stream(&state).error != zip.ErrorKind.End { #panic("ended ZIP loses End status") } }'])
CASES['csv-trailing-empty-stream'] = stream_support + '''
use "std/encoding/csv"
fn main() { input := Input{ bytes: "a," } buffer: [8]u8 = []
 state := csv.stream_scanner(io.Reader{ data: #cast(rawptr) &input, read: &read_input })
 _ = csv.next_stream(&state, buffer[..])
 last := csv.next_stream(&state, buffer[..])
 if !last.ok || #len(last.text) != 0 { #panic("stream loses final empty CSV field") } }
'''
CASES['http-close-body'] = stream_support + r'''
use "std/net/http"
fn main() { input := Input{ bytes: "HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nbody" }
 request_storage: [256]u8 = [] response_storage: [256]u8 = []
 response := http.client_do(io.Reader{ data: #cast(rawptr) &input, read: &read_input }, io.Writer{ write: &write_output }, request_storage[..], response_storage[..], "GET", "/", "test", "")
 if !response.ok || #len(response.body) != 4 { #panic("HTTP drops close-delimited body") } }
'''
# Generate a PNG whose outer chunk CRC is valid, but zlib Adler-32 is wrong.
import struct
import zlib
import tarfile
import io as pyio

def dyn_array(data):
    return '[' + ','.join(map(str, data)) + ']'
def png_chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
compressed = bytearray(zlib.compress(b'\x00\x7f'))
compressed[-1] ^= 1
png = b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', struct.pack('>IIBBBBB',1,1,8,0,0,0,0)) + png_chunk(b'IDAT',compressed) + png_chunk(b'IEND',b'')
CASES['png-adler'] = 'use "std/image/png"\nfn main() { source: [%d]u8 = %s\npixels: [1]u8 = [] compressed: [128]u8 = [] scanlines: [2]u8 = []\n if png.decode(pixels[..], compressed[..], scanlines[..], source[..]).ok { #panic("bad Adler checksum accepted") } }\n' % (len(png), dyn_array(png))
archive = pyio.BytesIO()
with tarfile.open(fileobj=archive, mode='w', format=tarfile.USTAR_FORMAT) as tar:
    tar.addfile(tarfile.TarInfo('entry'))
bad_tar = bytearray(archive.getvalue()[:512]); bad_tar[0] ^= 1
CASES['tar-checksum'] = 'use "std/archive/tar"\nfn main() { source: [%d]u8 = %s\n state := tar.reader(source[..])\n if tar.next(&state).status == tar.Status.Entry { #panic("bad TAR checksum accepted") } }\n' % (len(bad_tar),dyn_array(bad_tar))

CASES['runtime-deep-trace'] = '\n'.join([
 'fn recurse(depth: i32) { if depth > 0 { recurse(depth - 1) } }',
 'fn main() { recurse(70) #panic("trace must retain main") }'])

# Controls distinguish the suspected edge cases from a broken harness.
CASES['control-pem-newline'] = CASES['pem-final-line'].replace('-----END TEST-----"', '-----END TEST-----\\n"')
CASES['control-comment-free'] = CASES['comment-import-member'].replace('/* comment */', '')
CASES['control-path-absolute'] = CASES['path-dot-root'].replace('".", "file"', '"/tmp", "file"')
CASES['control-url-simple'] = CASES['url-relative-colon'].replace('path/to:file', 'path/to-file')
CASES['control-tar-checksum'] = CASES['tar-checksum'].replace(dyn_array(bad_tar), dyn_array(archive.getvalue()[:512])).replace('== tar.Status.Entry', '!= tar.Status.Entry')
CASES['control-runtime-shallow-trace'] = CASES['runtime-deep-trace'].replace('recurse(70)', 'recurse(10)')

# HKDF expansion must preserve the complete PRK across the HMAC block boundary.
for key_length in (32, 64, 100):
    prk = bytes(range(key_length))
    expected = hmac.new(prk, b'info\x01', hashlib.sha256).digest()
    CASES[f'hkdf-prk-{key_length}'] = ('use "std/crypto/kdf"\nuse "std/bytes"\nfn main() {\n'
        + f'key: [{key_length}]u8 = {dyn_array(prk)} expected: [32]u8 = {dyn_array(expected)}\n'
        + 'output: [32]u8 = [] scratch: [64]u8 = []\n'
        + 'result := kdf.hkdf_expand(output[..], key[..], "info", scratch[..])\n'
        + 'if !result || !bytes.equal(output[..], expected[..]) { #panic("HKDF complete PRK") }\n}\n')

def run(command):
    try:
        r = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, DYN_SDK=str(ROOT / 'compiler')))
        return {'exit': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr}
    except subprocess.TimeoutExpired:
        return {'timeout': True}

results = {}
for name, source in CASES.items():
    package = OUT / name
    package.mkdir(exist_ok=True)
    (package / 'main.dyn').write_text(source)
    results[name] = {}
    for mode in ('debug', 'release'):
        binary = package / mode
        build = run([str(DYN), 'build', str(package), '--no-cache', '--quiet', '--output', str(binary), *(['--release'] if mode == 'release' else [])])
        entry = {'build': build}
        if build.get('exit') == 0:
            entry['run'] = run([str(binary)])
        results[name][mode] = entry
        if build.get('exit') != 0:
            status = 'BUILD_FAILED'
        elif 'runtime-' in name:
            trace_ok = mode == 'release' or 'at main (' in entry['run']['stderr']
            status = 'PASS' if entry['run'].get('exit') == 101 and trace_ok else 'CONTRACT_FAILED'
        else:
            status = 'PASS' if entry['run'].get('exit') == 0 else 'CONTRACT_FAILED'
        entry['status'] = status
        print(f'{name} {mode}: {status}', flush=True)
(OUT / 'repro-results.json').write_text(json.dumps(results, indent=2) + '\n')

failures = [(name, mode) for name, modes in results.items() for mode, result in modes.items() if result["status"] != "PASS"]
if failures:
    raise SystemExit(f"Audit regressions failed: {failures}")
