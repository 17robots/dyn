#!/usr/bin/env python3
"""Official Unicode 17 normalization, folding and grapheme conformance vectors."""
import argparse, hashlib, io, os, struct, subprocess, tempfile, urllib.request, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn')).resolve())
archive=ROOT/'build/sdk-expansion/UCD-17.zip'
if not archive.exists():
 archive.parent.mkdir(parents=True,exist_ok=True)
 archive.write_bytes(urllib.request.urlopen('https://www.unicode.org/Public/17.0.0/ucd/UCD.zip').read())
raw=archive.read_bytes();assert hashlib.sha256(raw).hexdigest()=='2066d1909b2ea93916ce092da1c0ee4808ea3ef8407c94b4f14f5b7eb263d28e'
z=zipfile.ZipFile(io.BytesIO(raw));data=bytearray();count=0
def emit(mode,source,expected):
 global count
 data.extend(struct.pack('<III',mode,len(source),len(expected))+source+expected);count+=1
def encode(s): return ''.join(chr(int(x,16)) for x in s.split()).encode()
for line in z.read('NormalizationTest.txt').decode().splitlines():
 line=line.split('#')[0].strip()
 if not line or line.startswith('@'): continue
 c=[encode(x.strip()) for x in line.split(';')[:5]]
 for i in range(5):
  for mode,j in ((0,2 if i<3 else 4),(1,1 if i<3 else 3),(2,4),(3,3)): emit(mode,c[i],c[j])
for line in z.read('CaseFolding.txt').decode().splitlines():
 line=line.split('#')[0].strip()
 if not line: continue
 cp,status,mapping,*_=map(str.strip,line.split(';'))
 if status in ('C','F'): emit(4,encode(cp),encode(mapping))
for line in z.read('auxiliary/GraphemeBreakTest.txt').decode().splitlines():
 line=line.split('#')[0].strip()
 if not line: continue
 parts=line.split();source=bytearray();boundaries=[]
 for token in parts:
  if token=='÷': boundaries.append(len(source))
  elif token!='×': source.extend(chr(int(token,16)).encode())
 emit(5,source,b''.join(struct.pack('<I',x) for x in boundaries[1:]))
with tempfile.TemporaryDirectory(prefix='dyn-unicode-') as tmp:
 p=Path(tmp);(p/'cases.bin').write_bytes(data)
 source='''use "std/unicode/text" text
use "std/encoding/binary" binary
use "std/fs" fs
use "std/io" io
use "std/bytes" bytes
fn load(b: []const u8, at: usize) usize { return #cast(usize) b[at] | (#cast(usize) b[at+1] << 8) | (#cast(usize) b[at+2] << 16) | (#cast(usize) b[at+3] << 24) }
fn main() {
 file := fs.open("PATH") if !file.ok { #panic("open") } defer _ = fs.close(&file.file)
 reader := fs.reader(&file.file) header: [12]u8 = [] input: [4096]u8 = [] expected: [4096]u8 = [] output: [4096]u8 = [] work: [8192]u32 = []
 index: usize = 0
 for {
  record := io.read_exact(reader,header[..])
  if record.status == io.Status.End && record.transferred == 0 { break }
  if record.status != io.Status.Complete { #panic("header") }
  mode := load(header[..],0) n := load(header[..],4) m := load(header[..],8)
  if n > 4096 || m > 4096 { #panic("test capacity") }
  if io.read_exact(reader,input[..n]).status != io.Status.Complete || io.read_exact(reader,expected[..m]).status != io.Status.Complete { #panic("record") }
  if mode == 5 {
   iterator := text.graphemes(input[..n]) boundary: usize = 0
   for text.next_grapheme(&iterator).ok {
    if boundary + 4 > m || iterator.offset != load(expected[..m],boundary) { #panic("grapheme boundary") }
    boundary += 4
   }
   if boundary != m || iterator.error != text.ErrorKind.None { #panic("grapheme end") }
  } else {
   result := text.Result{}
   if mode == 4 { result = text.case_fold(output[..],input[..n]) }
   else {
    form := text.Form.NFD if mode == 1 { form = text.Form.NFC } else if mode == 2 { form = text.Form.NFKD } else if mode == 3 { form = text.Form.NFKC }
    result = text.normalize(output[..],input[..n],form,work[..])
   }
   if !result.ok || !bytes.equal(output[..result.written],expected[..m]) { #panic("Unicode conformance") }
  }
  index += 1
 }
 if index != COUNT { #panic("case count") }
}
'''.replace('PATH',str(p/'cases.bin')).replace('COUNT',str(count))
 (p/'main.dyn').write_text(source)
 for mode in ([],['--release']):
  subprocess.run([DYN,'build',str(p),'--quiet','--no-cache','--output',str(p/'run'),*mode],cwd=ROOT,check=True)
  subprocess.run([str(p/'run')],check=True,timeout=120)
print(f'PASS Unicode 17: {count} official normalization/folding/grapheme vectors, debug/release')
