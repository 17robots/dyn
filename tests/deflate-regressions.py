#!/usr/bin/env python3
"""Exercise circular streaming history against independent zlib/gzip fixtures."""
import gzip
import os
from pathlib import Path
import random
import subprocess
import tempfile
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build' / ('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve()
SOURCE = r'''use deflate "std/compress/deflate"
use gzip "std/compress/gzip"
use io "std/io"
use fs "std/fs"
use memory "std/mem"
fn require(ok: bool, message: []const u8) { if !ok { #panic(message) } }
struct Source { bytes: []const u8, at: usize, chunk: usize }
fn source_read(data: rawptr, destination: []u8) usize!io.IoErr {
  source := #cast(*Source, data)
  amount := source.bytes.len - source.at
  if amount > destination.len { amount = destination.len }
  if amount > source.chunk { amount = source.chunk }
  for i in 0..amount { destination[i] = source.bytes[source.at + i] }
  source.at += amount
  return amount
}
fn check(encoded: []const u8, expected: []const u8, wrapped: bool, corrupt: bool, chunk: usize, source_chunk: usize, history_size: usize) {
  source := Source{ bytes: encoded, chunk: source_chunk }
  reader := io.Reader{ data: #cast(rawptr, &source), read: source_read }
  compressed: [1024]u8
  history: [65536]u8
  output: [65536]u8
  state := deflate.decoder(reader, compressed[..], history[..history_size])
  if wrapped { state = gzip.decoder(reader, compressed[..], history[..history_size]) }
  decoder := deflate.decoder_reader(&state)
  empty := io.read(decoder, output[..0]) catch { #panic("zero destination") }
  require(empty == 0 && source.at == 0, "zero destination")
  total: usize = 0
  for {
    count := io.read(decoder, output[..chunk]) catch {
      require(corrupt, "unexpected decode error")
      return
    }
    require(total + count <= expected.len, "extra output")
    for i in 0..count { require(output[i] == expected[total + i], "output mismatch") }
    total += count
    if count == 0 {
      require(!corrupt && total == expected.len, "unexpected end")
      return
    }
  }
}
fn fixture(encoded_path: []const u8, expected_path: []const u8, wrapped: bool, corrupt: bool) {
  owned := memory.arena_alloc(4000000)
  encoded := fs.read_all(owned, encoded_path, 1000000) catch { #panic("cannot read a fixture") }
  expected := fs.read_all(owned, expected_path, 1000000) catch { #panic("cannot read a fixture") }
  chunks: [5]usize = [1, 257, 258, 33025, 65536]
  for chunk in chunks {
    check(encoded, expected, wrapped, corrupt, chunk, 7, 33026)
    // Bytewise output already exercises every boundary with minimum history.
    // Larger chunks cover the second storage/input configuration without
    // repeating millions of debug-mode reader calls on shared CI runners.
    if chunk != 1 { check(encoded, expected, wrapped, corrupt, chunk, 1024, 65536) }
  }
  if !wrapped && !corrupt {
    inflated := deflate.inflate(owned, encoded) catch { #panic("one-shot inflate") }
    require(inflated.value.len == expected.len, "one-shot inflate")
    for i in 0..inflated.value.len { require(inflated.value[i] == expected[i], "one-shot output") }
    destination := memory.push_bytes(owned, expected.len)
    result: deflate.Result
    progressive := deflate.InflateState{}
    prefix: usize = 0
    for prefix < encoded.len {
      prefix += 1024
      if prefix > encoded.len { prefix = encoded.len }
      result = deflate.resume(&progressive, destination, encoded[..prefix])
      require(progressive.error == 0, "linear resume error")
    }
    require(result.done && result.written == expected.len, "linear resume completion")
    for i in 0..destination.len { require(destination[i] == expected[i], "linear resume output") }
    tiny: [1]u8
    capacity := deflate.InflateState{}
    result = deflate.resume(&capacity, tiny[..], encoded)
    require(!result.done && capacity.error == -28, "linear output capacity")
  }
  memory.arena_release(owned)
}
fn main() {
CALLS
  io.println("deflate passed")
}
'''


def raw(payload, level=6, strategy=zlib.Z_DEFAULT_STRATEGY):
    encoder = zlib.compressobj(level, zlib.DEFLATED, -15, strategy=strategy)
    return encoder.compress(payload) + encoder.flush()


def distant_fixture():
    # A stored seed followed by fixed-Huffman references at RFC 1951's maximum
    # distance, plus overlapping distance-one references across circular wraps.
    seed = random.Random(17).randbytes(32768)
    result = bytearray(b'\x00\x00\x80\xff\x7f' + seed)
    bits = []

    def emit(value, width):
        bits.extend((value >> i) & 1 for i in range(width))

    def symbol(value):
        if value <= 143:
            code, width = 48 + value, 8
        elif value <= 255:
            code, width = 400 + value - 144, 9
        elif value <= 279:
            code, width = value - 256, 7
        else:
            code, width = 192 + value - 280, 8
        emit(int(f'{code:0{width}b}'[::-1], 2), width)

    emit(1, 1)
    emit(1, 2)
    expected = bytearray(seed)
    for distance in [32768] * 140 + [1] * 10:
        symbol(285)
        if distance == 32768:
            emit(int(f'{29:05b}'[::-1], 2), 5)
            emit(8191, 13)
        else:
            emit(0, 5)
        for _ in range(258):
            expected.append(expected[-distance])
    symbol(256)
    bits.extend([0] * ((-len(bits)) % 8))
    result.extend(sum(bits[i + j] << j for j in range(8)) for i in range(0, len(bits), 8))
    assert zlib.decompress(result, -15) == expected
    return bytes(result), bytes(expected)


with tempfile.TemporaryDirectory(prefix='dyn-deflate-') as temporary:
    work = Path(temporary)
    project = work / 'project'
    project.mkdir()
    # Keep multiple minimum-history wraps and a full 64 KiB wrap, while
    # bounding correctness-test work independently of throughput benchmarks.
    payload = (bytes(range(256)) * 260) + b'overlapping-backreference-' * 200
    assert len(payload) > 2 * 33026
    dynamic = raw(payload)
    assert (dynamic[0] >> 1) & 3 == 2
    distant, distant_plain = distant_fixture()
    assert len(distant_plain) > 2 * 33026
    wrapped = gzip.compress(payload, mtime=0) + gzip.compress(distant_plain, mtime=0)
    bad_crc = bytearray(wrapped)
    bad_crc[-8] ^= 1
    bad_size = bytearray(wrapped)
    bad_size[-4] ^= 1
    fixtures = [
        ('stored', raw(payload, level=0), payload, False, False),
        ('fixed', raw(payload, strategy=zlib.Z_FIXED), payload, False, False),
        ('dynamic', dynamic, payload, False, False),
        ('distant', distant, distant_plain, False, False),
        ('gzip-concatenated', wrapped, payload + distant_plain, True, False),
        ('gzip-crc', bad_crc, payload + distant_plain, True, True),
        ('gzip-size', bad_size, payload + distant_plain, True, True),
        ('truncated', dynamic[:-2], payload, False, True),
        ('invalid', b'\x07', b'', False, True),
    ]
    calls = []
    for name, encoded, expected, wrapped, corrupt in fixtures:
        (work / f'{name}.bin').write_bytes(encoded)
        (work / f'{name}.expected').write_bytes(expected)
        calls.append(f'  fixture("{name}.bin", "{name}.expected", {str(wrapped).lower()}, {str(corrupt).lower()})')
    (project / 'main.dyn').write_text(SOURCE.replace('CALLS', '\n'.join(calls)), encoding='utf-8')
    for mode in ('--debug', '--release'):
        output = work / ('deflate.exe' if os.name == 'nt' else 'deflate')
        subprocess.run([str(DYN), 'build', str(project), '--no-cache', '--quiet', '--output', str(output), mode], cwd=work, check=True, timeout=120)
        started = time.monotonic()
        result = subprocess.run([str(output)], cwd=work, capture_output=True, timeout=90)
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert result.stdout == b'deflate passed\n', result.stdout
        print(f"PASS deflate {mode}: {time.monotonic() - started:.2f}s", flush=True)
print('PASS deflate circular history, streaming blocks, backreferences, gzip and errors (debug/release)')
