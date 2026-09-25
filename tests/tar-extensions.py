#!/usr/bin/env python3
"""Python tarfile-produced PAX/GNU names through buffered and streaming readers."""
import io, os, subprocess, tarfile, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-tar-') as tmp:
 p=Path(tmp)
 for fmt in (tarfile.PAX_FORMAT,tarfile.GNU_FORMAT):
  buf=io.BytesIO();long='directory/'+'x'*220
  with tarfile.open(fileobj=buf,mode='w',format=fmt) as tar:
   info=tarfile.TarInfo(long);info.size=5;tar.addfile(info,io.BytesIO(b'hello'))
   link=tarfile.TarInfo('link');link.type=tarfile.SYMTYPE;link.linkname=long;tar.addfile(link)
  data=buf.getvalue()
  source='''use "std/archive/tar" tar
use "std/io" io
use "std/bytes" bytes
fn main() {
'''+f'data: [{len(data)}]u8 = ['+','.join(map(str,data))+']\n'+f'expected := "{long}"\n'+'''
 state := tar.reader(data[..]) first := tar.next(&state) second := tar.next(&state)
 if first.status != tar.Status.Entry || !bytes.equal(first.entry.name,expected) || !bytes.equal(first.entry.data,"hello") { #panic("buffered long path") }
 if second.status != tar.Status.Entry || !bytes.equal(second.entry.link_name,expected) { #panic("buffered long link") }
 if tar.next(&state).status != tar.Status.End { #panic("buffered end") }
 backing: [8192]u8 = []
 cursor := io.cursor(data[..]) header: [512]u8 = []
 stream := tar.stream_reader(io.cursor_reader(&cursor),header[..],backing[..])
 entry := tar.next_stream(&stream) output: [5]u8 = []
 if !entry.ok || !bytes.equal(entry.name,expected) || tar.read_stream(&stream,output[..]).status != io.Status.End || !bytes.equal(output[..],"hello") { #panic("stream long path") }
 other := tar.next_stream(&stream)
 if !other.ok || !bytes.equal(other.link_name,expected) { #panic("stream long link") }
 if tar.next_stream(&stream).ok { #panic("stream end") }
}
'''
  (p/'main.dyn').write_text(source)
  for mode in ([],['--release']):
   subprocess.run([DYN,'build',str(p),'--quiet','--no-cache','--output',str(p/'run'),*mode],cwd=ROOT,check=True)
   subprocess.run([str(p/'run')],check=True)
print('PASS PAX/GNU long paths and links, buffered/streaming, debug/release')
