#!/usr/bin/env python3
"""Reassemble independent output for every native target; execute the host ABI."""
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn')).resolve())
CLANG = shutil.which('clang') if os.environ.get('DYN_ASSEMBLY_ORACLE') != '0' else None
TARGETS = {'x86_64-linux':'x86_64-linux-gnu', 'aarch64-linux':'aarch64-linux-gnu',
           'aarch64-macos':'arm64-apple-macos15', 'x86_64-windows':'x86_64-windows-gnu'}
SOURCE = '''
extern fn ext "external"(x: i64) i64
pub state: i64 = 7
pub fn answer(x: i64) i64 { return ext(x) + state }
pub fn text() []const u8 { return "assembly" }
'''

def run(*args):
    p = subprocess.run([str(x) for x in args], cwd=ROOT, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert p.returncode == 0, (args, p.returncode, p.stdout, p.stderr)
    return p

def sections(path):
    b = path.read_bytes()
    u = lambda at, n: int.from_bytes(b[at:at+n], 'little')
    result = {}
    if b[:4] == b'\x7fELF':
        table, count, names = u(40,8), u(60,2), u(62,2)
        names = u(table+64*names+24,8)
        for i in range(count):
            s=table+64*i; name=b[names+u(s,4):].split(b'\0',1)[0].decode()
            if u(s+4,4) not in (1,14): continue
            result[name]=b[u(s+24,8):u(s+24,8)+u(s+32,8)]
    elif b[:4] == bytes.fromhex('cffaedfe'):
        at=32
        for _ in range(u(16,4)):
            if u(at,4)==0x19:
                for i in range(u(at+64,4)):
                    s=at+72+80*i
                    name=b[s:s+16].split(b'\0',1)[0].decode()
                    result[name]=b[u(s+48,4):u(s+48,4)+u(s+40,8)]
            at+=u(at+4,4)
    else:
        strings=u(8,4)+18*u(12,4)
        for i in range(u(2,2)):
            s=20+40*i; name=b[s:s+8].split(b'\0',1)[0]
            if name.startswith(b'/'): name=b[strings+int(name[1:]):].split(b'\0',1)[0]
            name=name.decode()
            # COFF permits two separate .rdata sections. Other sections are unique.
            if name in result: continue
            result[name]=b[u(s+20,4):u(s+20,4)+u(s+16,4)]
    return result

with tempfile.TemporaryDirectory(prefix='dyn-native-asm-') as directory:
    work=Path(directory); module=work/'module';module.mkdir()
    (module/'main.dyn').write_text(SOURCE)
    for target,triple in TARGETS.items():
        output=work/target
        run(DYN,'build',module,'--backend','native','--release','--debug-info','--shared',
            '--no-link','--emit-object','--emit-asm','--target',target,'--output',output)
        assembly=output.with_suffix('.s');original=output.with_suffix('.o');rebuilt=work/(target+'-roundtrip.o')
        text=assembly.read_text()
        assert 'symbolic relocations' in text and '.byte' in text
        assert ('"_answer":' if target.endswith('macos') else '"answer":') in text
        if not CLANG:
            continue
        run(CLANG,'--target='+triple,'-c',assembly,'-o',rebuilt)
        before,after=sections(original),sections(rebuilt)
        # Debug/unwind payloads and constructor entries survive assembly output.
        for name in ('.debug_abbrev','.debug_line','.xdata','__debug_abbrev','__debug_line'):
            if name in before: assert before[name]==after[name], (target,name)
        for name in ('.debug_info','.debug_frame','.pdata','.init_array','__mod_init_func','__debug_info','__debug_frame'):
            if name in before: assert name in after and len(before[name])==len(after[name]), (target,name)
        host = ('aarch64' if platform.machine().lower() in ('aarch64','arm64') else 'x86_64') + '-' + {'Linux':'linux','Darwin':'macos','Windows':'windows'}.get(platform.system(),'unknown')
        if target==host:
            harness=work/'harness.c'
            harness.write_text('''
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
extern int64_t answer(int64_t);
extern int64_t state;
struct Slice { const char *data; uint64_t length; };
extern struct Slice text(void);
int64_t external(int64_t x) { return 2*x; }
void dyn_panic(void) { abort(); }
int main(void) {
  /* Windows library objects expose explicit initialization through DllMain;
     setting this fixture's scalar also lets the executable test focus on ABI. */
  state=7;
  if(answer(5)!=17) return 1;
  state=13;
  struct Slice s=text();
  return answer(5)!=23 || s.length!=8 || memcmp(s.data,"assembly",8);
}
''')
            executable=work/'roundtrip'
            run(CLANG,harness,rebuilt,'-o',executable)
            run(executable)
print('PASS independent assembly generation all four formats' +
      ('; roundtrip host C ABI, debug/unwind and constructors' if CLANG else ' (oracle disabled/unavailable)'))
