#!/usr/bin/env python3
"""Metadata memory is independent of entry count, including global PAX updates."""
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
# Keep archive construction independent of the Dyn reader.
def record(kind, data, name='entry'):
    info = tarfile.TarInfo(name); info.type = kind; info.size = len(data)
    return info.tobuf(format=tarfile.USTAR_FORMAT) + data + b'\0' * (-len(data) % 512)
def pax(key, value):
    suffix = f' {key}={value}\n'.encode(); length = len(suffix) + 1
    while len(str(length)) + len(suffix) != length: length = len(str(length)) + len(suffix)
    return str(length).encode() + suffix
segment = record(tarfile.XGLTYPE, pax('path', 'global')) + record(tarfile.XHDTYPE, pax('path', 'local')) + record(tarfile.REGTYPE, b'') + record(tarfile.REGTYPE, b'')
source = '''use "std/archive/tar" tar
use "std/bytes" bytes
use "std/io" io
fn main() {
'''+f'data: [{len(segment)}]u8 = ['+','.join(map(str, segment))+''']
 header: [512]u8 = [] metadata: [128]u8 = []
 cursor := io.cursor(data[..])
 state := tar.stream_reader(io.cursor_reader(&cursor), header[..], metadata[..])
 iteration: usize = 0
 for iteration < 2000 {
   cursor.offset = 0
   first := tar.next_stream(&state)
   if !first.ok || !bytes.equal(first.name, "local") { #panic("local metadata") }
   second := tar.next_stream(&state)
   if !second.ok || !bytes.equal(second.name, "global") { #panic("global metadata") }
   if state.metadata_used > 12 { #panic("unbounded metadata") }
   iteration += 1
 }
 cursor.offset = 0
 small := tar.stream_reader(io.cursor_reader(&cursor), header[..], metadata[..8])
 exhausted := tar.next_stream(&small) offset := cursor.offset
 if exhausted.ok || exhausted.error != -28 { #panic("metadata capacity") }
 if tar.next_stream(&small).error != -28 || cursor.offset != offset { #panic("sticky capacity") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-tar-memory-') as directory:
    root = Path(directory); (root/'main.dyn').write_text(source)
    for mode in ([], ['--release']):
        subprocess.run([str(Path(os.environ.get('DYN', ROOT/'build/dyn')).resolve()), 'build', str(root), '--quiet', '--no-cache', '--output', str(root/'run'), *mode], check=True)
        subprocess.run([str(root/'run')], check=True, timeout=10)
print('PASS 4000 TAR entries in 128 metadata bytes; global/local compaction, capacity and sticky errors, debug/release')
