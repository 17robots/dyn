#!/usr/bin/env python3
"""Run expansion contract fixtures on the native host, without cross-toolchains.

Reuse each result suite's fixture-definition prefix; its top-level temporary
build/execution block is deliberately excluded. This keeps the independent
vectors identical to the full suites while avoiding their cross-target matrix.
"""
import ast
import io
import math
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[1]
SUFFIX = '.exe' if os.name == 'nt' else ''
DYN = str(Path(os.environ.get('DYN', ROOT / ('build/dyn-release' + SUFFIX))).resolve())
ENV = dict(os.environ, DYN_SDK=str(ROOT))


def fixture(name):
    path = ROOT / 'tests' / name
    parsed = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    prefix = []
    for statement in parsed.body:
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            break
        prefix.append(statement)
    else:
        raise AssertionError(f'{name}: expected top-level fixture/execution boundary')
    namespace = {'__file__': str(path), '__name__': 'host_fixture'}
    exec(compile(ast.Module(body=prefix, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def dyn_bytes(data):
    return '"' + ''.join(f'\\x{x:02x}' for x in data) + '"'


def segment(marker, payload):
    return bytes([255, marker]) + struct.pack('>H', len(payload) + 2) + payload


# Minimal independently specified baseline JPEG: DC0/EOB0, then six one pad bits.
jpeg = (b'\xff\xd8' + segment(219, b'\0' + bytes([1]) * 64)
        + segment(192, bytes([8, 0, 1, 0, 1, 1, 1, 17, 0]))
        + segment(196, bytes([0, 1]) + bytes(15) + b'\0'
                  + bytes([16, 1]) + bytes(15) + b'\0')
        + segment(218, bytes([1, 1, 0, 0, 63, 0])) + b'\x3f\xff\xd9')
gif = (b'GIF89a\x01\0\x01\0\x80\0\0\xff\0\0\0\0\0'
       b',\0\0\0\0\x01\0\x01\0\0\x02\x02\x44\x01\0;')
FORMATS = r'''use "std/image/bmp" bmp
use "std/image/tga" tga
use "std/image/gif" gif
use "std/image/jpeg" jpeg
use "std/encoding/toml" toml
use "std/mem" mem
use "std/bytes" bytes
fn check(ok: bool) { if !ok { #panic("host formats") } }
fn main() {
 arena := mem.Arena{}
 defer { mem.arena_release(&arena) }
 pixels: [8]u8 = [255,0,0,255,0,128,255,64]
 bitmap := bmp.encode(&arena,pixels[..],2,1,4)
 check(bitmap.ok)
 decoded := bmp.decode(&arena,bitmap.value)
 check(decoded.ok && bytes.equal(decoded.value.pixels,pixels[..]))
 targa := tga.encode(&arena,pixels[..],2,1,4)
 check(targa.ok)
 uncompressed := tga.decode(&arena,targa.value)
 check(uncompressed.ok && bytes.equal(uncompressed.value.pixels,pixels[..]))
 animation := gif.decode(&arena,GIF_BYTES)
 check(animation.ok && bytes.equal(animation.value.pixels,"\xff\0\0\xff"))
 photo := jpeg.decode(&arena,JPEG_BYTES)
 check(photo.ok && bytes.equal(photo.value.pixels,"\x80\x80\x80\xff"))
 mark := mem.arena_mark(&arena)
 check(!bmp.decode(&arena,"BM").ok && mem.arena_mark(&arena)==mark)
 check(!tga.decode(&arena,"bad").ok && mem.arena_mark(&arena)==mark)
 check(!gif.decode(&arena,"GIF89a").ok && mem.arena_mark(&arena)==mark)
 check(!jpeg.decode(&arena,"\xff\xd8").ok && mem.arena_mark(&arena)==mark)
 document := toml.parse(&arena,"[owner]\nname='Dyn'\nports=[8000,8001]\n[[products]]\nx=1979-05-27T07:32:00Z\n")
 check(document.ok)
 owner := toml.member(document.root,"owner")
 check(bytes.equal(toml.member(owner,"name").text,"Dyn"))
 check(bytes.equal(toml.index(toml.member(owner,"ports"),1).text,"8001"))
 encoded := toml.encode(&arena,document.root)
 check(encoded.ok && toml.parse(&arena,encoded.value).ok)
 before := mem.arena_mark(&arena)
 check(!toml.parse(&arena,"a=1\na=2").ok && mem.arena_mark(&arena)==before)
}
'''.replace('GIF_BYTES', dyn_bytes(gif)).replace('JPEG_BYTES', dyn_bytes(jpeg))

cases = []
for script, key in (
    ('crypto-results.py', 'AEAD'), ('crypto-results.py', 'KEYS'),
    ('curve25519-results.py', 's'), ('p256-results.py', 's'),
    ('x509-results.py', 'SOURCE'), ('der-pem-results.py', 'SOURCE'),
    ('image-results.py', 'SOURCE'), ('pnm-results.py', 'SOURCE'),
    ('wav-results.py', 'source'), ('cbor-results.py', 'SOURCE'),
    ('msgpack-results.py', 'SOURCE'), ('protobuf-results.py', 'SOURCE'),
    ('text-layout.py', 'SOURCE'),
):
    cases.append((script.removesuffix('.py') + '-' + key.lower(), fixture(script)[key]))
font = fixture('font-results.py')
for long_loca, cmap12 in ((False, False), (True, True)):
    data, _ = font['fixture'](long_loca, cmap12)
    declaration = 'data: [' + str(len(data)) + ']u8 = [' + ','.join(map(str, data)) + ']\n'
    cases.append(('font-' + ('long' if long_loca else 'short'), declaration + font['SOURCE']))
cases.append(('bmp-tga-gif-jpeg-toml', FORMATS))

for script in ('ui-box-edit.py', 'ui-box-extras.py', 'ui-box-cache.py', 'ui-box-ime.py', 'text-edit-results.py', 'ui-box-correction.py'):
    cases.append((script.removesuffix('.py'), fixture(script)['SOURCE']))
system = fixture('font-system-results.py')
system_regular = system['face']('Test 😀', mono=True)
system_bold = system['face']('Test 😀', 'Bold Italic', 700, True, True)
system_invalid = system['face'](b'\xd8\x00\x00A')
declarations = ''.join(f'{name}: [{len(data)}]u8 = [{",".join(map(str, data))}]\n'
                       for name, data in [('regular_data', system_regular), ('bold_data', system_bold), ('invalid_data', system_invalid)])
cases.append(('font-system-metadata', declarations + system['SOURCE']))
cases.append(('font-system-scan', system['SCAN_SOURCE'].replace('FONT_DIRECTORY', 'fonts')))

with tempfile.TemporaryDirectory(prefix='dyn-expansion-host-') as directory:
    work = Path(directory)
    for name, source in cases:
        project = work / name
        project.mkdir()
        (project / 'main.dyn').write_text(source, encoding='utf-8')
        if name == 'font-system-scan':
            fonts = project / 'fonts'
            (fonts / 'nested').mkdir(parents=True)
            (fonts / 'regular.TTF').write_bytes(system_regular)
            (fonts / 'nested/bold.ttf').write_bytes(system_bold)
            (fonts / 'invalid.ttf').write_bytes(system_invalid)
            (fonts / 'ignored.txt').write_bytes(system_regular)
        if name == 'wav-results-source':
            reference = io.BytesIO()
            with wave.open(reference, 'wb') as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(22050)
                writer.writeframes(struct.pack('<5h', -32768, -16384, 0, 16384, 32767))
            (project / 'reference.wav').write_bytes(reference.getvalue())
        for flags in (['--debug'], ['--release'], ['--release', '--opt-level', '3']):
            output = project / ('program' + SUFFIX)
            subprocess.run([DYN, 'build', str(project), *flags, '--quiet', '--no-cache',
                            '--output', str(output)], env=ENV, check=True, timeout=300)
            subprocess.run([str(output)], cwd=project, env=ENV, check=True, timeout=180)
            if name == 'wav-results-source':
                for bits in (8, 16, 24, 32):
                    with wave.open(str(project / f'{bits}.wav'), 'rb') as decoded:
                        assert (decoded.getnchannels(), decoded.getframerate(), decoded.getnframes()) == (2, 48000, 3)
                        maximum = 1 << (bits - 1)
                        values = [min(maximum - 1, max(-maximum, math.floor(x * maximum + 0.5)))
                                  for x in (-1, -.5, 0, .25, .5, 1)]
                        expected = b''.join(bytes([x + 128]) if bits == 8 else x.to_bytes(bits // 8, 'little', signed=True)
                                            for x in values)
                        assert decoded.readframes(3) == expected
        print('PASS native host ' + name + ': debug/O2/O3', flush=True)
print('PASS std expansion native host: crypto, certificates, image/audio/wire formats, TOML, fonts and text layout')
