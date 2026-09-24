#!/usr/bin/env python3
"""PAX precedence/deletion/size and malformed extension contracts."""
import os,subprocess,tarfile,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn')).resolve())
def record(name,kind,payload,header_size=None):
 info=tarfile.TarInfo(name);info.type=kind;info.size=len(payload) if header_size is None else header_size
 return info.tobuf(format=tarfile.USTAR_FORMAT)+payload+b'\0'*((-len(payload))%512)
def pax(values):
 result=b''
 for key,value in values.items():
  suffix=f' {key}={value}\n'.encode();length=len(suffix)+1
  while len(str(length))+len(suffix)!=length:length=len(str(length))+len(suffix)
  result+=str(length).encode()+suffix
 return result
valid=record('global',tarfile.XGLTYPE,pax({'path':'global'}))+record('one',tarfile.REGTYPE,b'x')+record('local',tarfile.XHDTYPE,pax({'path':'','size':'4'}))+record('two',tarfile.REGTYPE,b'data',0)+record('three',tarfile.REGTYPE,b'')+b'\0'*1024
invalid=[record('bad',tarfile.XHDTYPE,b'999 path=x\n'),record('pending',tarfile.XHDTYPE,pax({'path':'x'}))+b'\0'*512,record('bad',tarfile.GNUTYPE_LONGNAME,b''),record('bad',tarfile.GNUTYPE_LONGLINK,b'a\0b\0'),record('sparse',tarfile.XHDTYPE,pax({'GNU.sparse.size':'99'}))]
with tempfile.TemporaryDirectory(prefix='dyn-pax-') as tmp:
 p=Path(tmp);source='use "std/archive/tar" tar\nuse "std/bytes" bytes\nuse "std/io" io\n'
 for index,data in enumerate([valid,*invalid]):
  source+=f'fn case_{index}() {{ data: [{len(data)}]u8 = ['+','.join(map(str,data))+']\nstate := tar.reader(data[..])\n'
  if index==0:
   source+='''first := tar.next(&state) second := tar.next(&state) third := tar.next(&state)
 if first.status != tar.Status.Entry || !bytes.equal(first.entry.name,"global") || second.status != tar.Status.Entry || !bytes.equal(second.entry.name,"two") || !bytes.equal(second.entry.data,"data") || third.status != tar.Status.Entry || !bytes.equal(third.entry.name,"global") { #panic("PAX precedence") }
 backing: [4096]u8 = [] header: [512]u8 = [] cursor := io.cursor(data[..])
 stream := tar.stream_reader(io.cursor_reader(&cursor),header[..],backing[..])
 a := tar.next_stream(&stream) if !a.ok || !bytes.equal(a.name,"global") { #panic("stream global") }
 b := tar.next_stream(&stream) out: [4]u8 = []
 if !b.ok || !bytes.equal(b.name,"two") || b.size != 4 || tar.read_stream(&stream,out[..]).status != io.Status.End || !bytes.equal(out[..],"data") { #panic("stream local delete/size") }
 c := tar.next_stream(&stream) if !c.ok || !bytes.equal(c.name,"global") { #panic("stream retained global") }
'''
  else:source+='result := tar.next(&state) if result.status != tar.Status.Error || state.offset != 0 { #panic("malformed extension") }\n'
  source+='}\n'
 source+='fn main() { '+' '.join(f'case_{i}()' for i in range(1+len(invalid)))+' }\n';(p/'main.dyn').write_text(source)
 for mode in ([],['--release']):
  subprocess.run([DYN,'build',str(p),'--quiet','--no-cache','--output',str(p/'run'),*mode],cwd=ROOT,check=True)
  subprocess.run([str(p/'run')],check=True)
print('PASS PAX global/local precedence, deletion, size override, malformed metadata, debug/release')
