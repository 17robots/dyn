#!/usr/bin/env python3
"""Independent ZIP/TAR producers exercise metadata and malformed input."""
import io, os, struct, subprocess, tempfile, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn')).resolve())
class Stream(io.BytesIO):
 def seekable(self): return False
 def seek(self,*args): raise io.UnsupportedOperation()
fixtures=[]
for streaming in (False,True):
 for compression in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):
  buf=Stream() if streaming else io.BytesIO()
  with zipfile.ZipFile(buf,'w',compression=compression) as z:
   z.writestr('file.txt',b'hello world');z.writestr('empty',b'');z.comment=b'comment'
  data=buf.getvalue();fixtures.append((data,True))
  damaged=bytearray(data);central=damaged.index(b'PK\1\2');damaged[central+46]^=1;fixtures.append((damaged,False))
  fixtures.append((data[:-1],False))
  if streaming:
   damaged=bytearray(data);desc=damaged.index(b'PK\7\10');damaged[desc+4]^=1;fixtures.append((damaged,False))
# Descriptor without optional signature, produced by stripping it from zipfile output.
buf=Stream()
with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED) as z: z.writestr('file.txt',b'hello world');z.writestr('empty',b'')
original=buf.getvalue();removed=original.index(b'PK\7\10');unsigned=bytearray(original[:removed]+original[removed+4:])
central=unsigned.index(b'PK\1\2');end=unsigned.rindex(b'PK\5\6')
struct.pack_into('<I',unsigned,end+16,central)
second=unsigned.index(b'PK\1\2',central+4)
struct.pack_into('<I',unsigned,second+42,struct.unpack_from('<I',unsigned,second+42)[0]-4)
fixtures.append((unsigned,True))
# Large extra field forces the low-level stream reader to reuse its header buffer.
buf=io.BytesIO()
with zipfile.ZipFile(buf,'w') as z:
 info=zipfile.ZipInfo('file.txt');info.extra=struct.pack('<HH',0x1234,200)+b'x'*200
 z.writestr(info,b'hello world');z.writestr('empty',b'')
fixtures.append((buf.getvalue(),True))
with tempfile.TemporaryDirectory(prefix='dyn-archives-') as tmp:
 p=Path(tmp);source='use "std/archive/zip" zip\nuse "std/bytes" bytes\nuse "std/io" io\n'
 for index,(data,ok) in enumerate(fixtures):
  source+=f'fn check_{index}() {{ data: [{len(data)}]u8 = ['+','.join(map(str,data))+']\n'
  source+=f' opened := zip.open_checked(data[..]) if opened.ok != {str(ok).lower()} {{ #panic("open {index}") }}\n'
  if ok:
   source+='first := zip.next(&opened.reader) out: [64]u8 = [] result := zip.extract(out[..],first.entry) if !first.ok || !result.ok || !bytes.equal(result.data,"hello world") { #panic("extract") }\nsecond := zip.next(&opened.reader) if !second.ok || second.entry.uncompressed_size != 0 { #panic("empty") }\nend := zip.next(&opened.reader) if end.ok || end.error != zip.ErrorKind.End { #panic("end") }\n'
  if index==len(fixtures)-1:
   source+='cursor := io.cursor(data[..]) header: [30]u8 = [] name: [64]u8 = [] payload: [64]u8 = []\nstream := zip.stream_reader(io.cursor_reader(&cursor),header[..],name[..],payload[..]) streamed := zip.next_stream(&stream) decoded := zip.extract(out[..],streamed.entry) if !streamed.ok || !decoded.ok || !bytes.equal(decoded.data,"hello world") { #panic("stream extra metadata") }\n'
  source+='}\n'
 source+='fn main() { '+' '.join(f'check_{i}()' for i in range(len(fixtures)))+' }\n';(p/'main.dyn').write_text(source)
 for mode in ([],['--release']):
  subprocess.run([DYN,'build',str(p),'--quiet','--no-cache','--output',str(p/'run'),*mode],cwd=ROOT,check=True)
  subprocess.run([str(p/'run')],check=True)
print('PASS ZIP central directory and descriptors, independent stored/deflated fixtures, debug/release')
