#!/usr/bin/env python3
"""ARM64 COFF import thunks and signed relocation addends, under sanitizers."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
clang = shutil.which(os.environ.get('CLANG', 'clang'))
if not clang:
    raise SystemExit('SKIP ARM64 COFF oracle: Clang unavailable')

def run(*args):
    return subprocess.run(list(map(str,args)),check=True,capture_output=True,text=True)

with tempfile.TemporaryDirectory(prefix='dyn-arm64-coff-') as directory:
    work = Path(directory)
    (work/'link.c').write_text('''#include "link_coff.h"
#include <string.h>
int main(int n,char **v) {
  DynCoffOptions o={.entry="dyn_start"};int first=2;
  if(n>2&&!strcmp(v[2],"--dll")) {o.shared=1;o.entry="imported";o.dll_name="provider.dll";o.import_library=v[3];first=4;}
  return dyn_link_coff((const char *const *)(v+first),n-first,v[1],&o);
}
''')
    run(clang,'-std=c11','-D_POSIX_C_SOURCE=200809L','-g','-O1',
        '-fsanitize=address,undefined','-fno-sanitize-recover=all',
        '-I'+str(ROOT/'src'),work/'link.c',ROOT/'src/link_coff.c','-o',work/'link')
    (work/'provider.s').write_text('.text\n.globl imported\nimported:\n ret\n')
    (work/'client.s').write_text('.text\n.globl dyn_start\ndyn_start:\n bl imported\n adrp x0, imported\n ret\n.data\n.globl imported_pointer\nimported_pointer: .quad imported\n')
    for name in ('provider','client'):
        run(clang,'--target=aarch64-pc-windows-msvc','-c',work/(name+'.s'),'-o',work/(name+'.o'))
    run(work/'link',work/'provider.dll','--dll',work/'provider.lib',work/'provider.o')
    # A direct call through the short-import member requires a defined code thunk.
    run(work/'link',work/'client.exe',work/'client.o',work/'provider.lib')
    pe = (work/'client.exe').read_bytes()
    header = struct.unpack_from('<I',pe,0x3c)[0]
    assert struct.unpack_from('<H',pe,header+4)[0] == 0xaa64
    assert b'provider.dll\0' in pe and b'imported\0' in pe
    def policy(path):
        data=path.read_bytes();header=struct.unpack_from('<I',data,0x3c)[0];opt=header+24
        versions=struct.unpack_from('<HH',data,opt+40)+struct.unpack_from('<HH',data,opt+48)
        flags=struct.unpack_from('<H',data,opt+70)[0]
        return data,header,opt,versions,flags
    # Microsoft's /DYNAMICBASE documentation forbids disabling ASLR on ARM64.
    # NX and OS/subsystem versions are independently compared with LLD below.
    for image in ('client.exe','provider.dll'):
        data,header,opt,versions,flags=policy(work/image)
        assert versions==(6,0,6,0), (image,versions)
        assert flags&0x160==0x160, (image,flags)
    data,header,opt,_,_=policy(work/'client.exe')
    reloc_rva,reloc_size=struct.unpack_from('<II',data,opt+112+5*8)
    assert reloc_rva and reloc_size>=12, 'ARM64 executable absolute pointers need ASLR fixups'
    section_count=struct.unpack_from('<H',data,header+6)[0]
    for i in range(section_count):
        section=opt+240+i*40
        va,raw_size,raw=struct.unpack_from('<III',data,section+12)
        if va<=reloc_rva<va+raw_size:
            offset=raw+reloc_rva-va
            assert struct.unpack_from('<H',data,offset+8)[0]>>12==10, 'expected DIR64 fixup'
            break
    else: raise AssertionError('unmapped base relocation directory')
    lld=shutil.which('lld-link')
    if lld:
        run(lld,'/machine:arm64','/entry:dyn_start','/subsystem:console','/nodefaultlib',
            '/out:'+str(work/'reference.exe'),work/'client.o',work/'provider.lib')
        _,_,_,versions,flags=policy(work/'reference.exe')
        assert versions==policy(work/'client.exe')[3]
        assert flags&0x160==policy(work/'client.exe')[4]&0x160
    # COFF's instruction carries the signed implicit addend. Clang refuses a
    # source-level nonzero branch offset, so mutate only its encoded immediate.
    obj = bytearray((work/'client.o').read_bytes())
    count = struct.unpack_from('<H',obj,2)[0]
    for i in range(count):
        section=20+i*40
        if obj[section:section+8].rstrip(b'\0') == b'.text':
            offset=struct.unpack_from('<I',obj,section+20)[0]
            struct.pack_into('<II',obj,offset,0x97ffffff,0xf0ffffe0) # BL -4; ADRP byte addend -1
            break
    else:
        raise AssertionError('missing text section')
    # Clang lowers a local symbol to a section symbol plus byte addend in
    # ADRP, even though the linked instruction interprets it in pages.
    (work/'offset.s').write_text('.text\n.globl dyn_start\ndyn_start:\n adrp x0, .Lmessage\n add x0, x0, :lo12:.Lmessage\n ret\n.section .rdata,"dr"\n.space 5000\n.Lmessage: .asciz "offset-marker"\n')
    run(clang,'--target=aarch64-pc-windows-msvc','-c',work/'offset.s','-o',work/'offset.o')
    run(work/'link',work/'offset.exe',work/'offset.o')
    def addressed_marker(path):
        data,header,opt,_,_=policy(path)
        entry=struct.unpack_from('<I',data,opt+16)[0]
        sections=[]
        for i in range(struct.unpack_from('<H',data,header+6)[0]):
            at=opt+240+i*40
            va,size,raw=struct.unpack_from('<III',data,at+12)
            sections.append((va,size,raw))
        def contents(rva):
            for va,size,raw in sections:
                if va<=rva<va+size:return raw+rva-va
            raise AssertionError(('unmapped address',hex(rva)))
        adrp,add=struct.unpack_from('<II',data,contents(entry))
        immediate=((adrp>>29)&3)|(((adrp>>5)&0x7ffff)<<2)
        if immediate&(1<<20):immediate-=1<<21
        destination=(entry&~4095)+immediate*4096+((add>>10)&4095)
        at=contents(destination)
        assert data[at:at+14]==b'offset-marker\0', (path,hex(destination))
    addressed_marker(work/'offset.exe')
    if lld:
        run(lld,'/machine:arm64','/entry:dyn_start','/subsystem:console','/nodefaultlib',
            '/out:'+str(work/'offset-reference.exe'),work/'offset.o')
        addressed_marker(work/'offset-reference.exe')
    (work/'negative.o').write_bytes(obj)
    run(work/'link',work/'negative.exe',work/'negative.o',work/'provider.lib')
print('PASS ARM64 COFF imported code thunks and negative branch/page and cross-page byte addends, ARM64 loader policy and EXE ASLR fixups under ASan/UBSan')
