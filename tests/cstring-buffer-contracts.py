#!/usr/bin/env python3
"""Fixed C-string buffers preserve capacities, borrowing and recoverable failure."""
import ctypes.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
ENV = dict(os.environ, DYN_SDK=str(ROOT))

SOURCE = r'''use "std/c" c
use "std/mem" mem
use "std/fs" fs
fn check(ok:bool) { if !ok { #panic("CString buffer contract") } }
fn main() {
 backing:[6]u8=[]
 mem.fill(backing[..],165)
 exact:=c.string_into(backing[1..5],"abc")
 check(exact.ok && exact.error==c.ErrorKind.None && exact.required==4 && exact.value==&backing[1])
 check(mem.equal(backing[1..5],"abc\x00") && backing[0]==165 && backing[5]==165)
 empty:=c.string_into(backing[1..2],"")
 check(empty.ok && empty.required==1 && empty.value==&backing[1] && backing[1]==0)
 check(backing[0]==165 && backing[2]=='b' && backing[5]==165)
 mem.fill(backing[..],165)
 short:=c.string_into(backing[1..4],"abc")
 check(!short.ok && short.error==c.ErrorKind.Capacity && short.required==4 && short.value==nil)
 zero:=c.string_into(backing[..0],"")
 check(!zero.ok && zero.error==c.ErrorKind.Capacity && zero.required==1 && zero.value==nil)
 invalid:=c.string_into(backing[..],"a\x00b")
 check(!invalid.ok && invalid.error==c.ErrorKind.InvalidInput && invalid.value==nil)
 for byte in backing { check(byte==165) }
 _=mem.copy(backing[..],"abcde!")
 overlap:=c.string_into(backing[1..5],backing[..3])
 check(overlap.ok && overlap.value==&backing[1] && mem.equal(backing[..],"aabc\x00!"))
 reverse:=c.string_into(backing[..4],backing[1..4])
 check(reverse.ok && reverse.value==&backing[0] && mem.equal(backing[..],"abc\x00\x00!"))
 before:[6]u8=[]
 _=mem.copy(before[..],backing[..])
 alias_invalid:=c.string_into(backing[1..],backing[..5])
 check(!alias_invalid.ok && alias_invalid.error==c.ErrorKind.InvalidInput && mem.equal(backing[..],before[..]))
 huge:=(&backing[0])[..~#cast(usize,0)]
 overflow:=c.string_into(backing[..],huge)
 check(!overflow.ok && overflow.error==c.ErrorKind.Overflow && overflow.value==nil && mem.equal(backing[..],before[..]))
 path:[4300]u8=[]
 mem.fill(path[..],'a')
 removed:=fs.remove(path[..])
 check(!removed.ok)
 for byte in path { check(byte=='a') }
}
'''
SQLITE = r'''use "vendor/sqlite" sqlite
fn main() {
 backing:[11]u8=[]
 for *byte in backing { byte.*=165 }
 result:=sqlite.open(":memory:",backing[1..10])
 if !result.ok || result.database==nil { #panic("SQLite exact CString buffer") }
 if backing[0]!=165 || backing[10]!=165 { #panic("SQLite CString canaries") }
 if sqlite.close(result.database)!=0 { #panic("SQLite close") }
}
'''


def run(work, name, source):
    project = work / name
    project.mkdir()
    (project / 'main.dyn').write_text(source)
    for mode in ('debug', 'release'):
        output = project / ('program.exe' if os.name == 'nt' else 'program')
        subprocess.run([DYN, 'build', str(project), '--' + mode, '--quiet',
                        '--no-cache', '--output', str(output)], cwd=ROOT,
                       env=ENV, check=True, timeout=120)
        result = subprocess.run([str(output)], capture_output=True, timeout=15)
        assert result.returncode == 0, (name, mode, result.returncode, result.stdout, result.stderr)
        print('PASS CString ' + name + ' ' + mode, flush=True)


with tempfile.TemporaryDirectory(prefix='dyn-cstring-buffers-') as temporary:
    work = Path(temporary)
    run(work, 'core-and-filesystem', SOURCE)
    names = re.findall(r'symbol\(loader, "([^"]+)"\)',
                       (ROOT / 'vendor/opengl/opengl.dyn').read_text())
    assert names and len(set(names)) == len(names)
    gl = '''use "vendor/opengl" gl
use "std/c" c
use "std/mem" mem
const names:[COUNT][]const u8=[NAMES]
visited:usize=0
fail_second:bool=false
fn loader(name:*const u8) rawptr {
 text:=c.bytes_from_string(name,64)
 if !text.ok || visited>=#len(names) || !mem.equal(text.value,names[visited]) { #panic("OpenGL CString loader") }
 visited+=1
 if fail_second && visited==2 { return nil }
 return #cast(rawptr,1)
}
fn main() {
 none:=gl.load(nil)
 if none.ok || !mem.equal(none.missing,"loader") || visited!=0 { #panic("nil loader") }
 loaded:=gl.load(loader)
 if !loaded.ok || visited!=#len(names) { #panic("OpenGL complete table") }
 visited=0
 fail_second=true
 failed:=gl.load(loader)
 if failed.ok || visited!=2 || !mem.equal(failed.missing,names[1]) { #panic("OpenGL missing symbol") }
}
'''.replace('COUNT', str(len(names))).replace('NAMES', ','.join(json.dumps(n) for n in names))
    run(work, 'opengl-loader', gl)
    # The std/provider implementation is optional; report its absence explicitly.
    cc = shlex.split(os.environ.get('CC', 'cc'))
    if not ctypes.util.find_library('sqlite3') or not cc or not shutil.which(cc[0]):
        print('SKIP CString SQLite exact buffer: missing sqlite3 provider or C linker', flush=True)
    else:
        probe = work / 'sqlite-provider.c'
        probe.write_text('extern int sqlite3_libversion_number(void); int main(void) { return sqlite3_libversion_number() <= 0; }\n')
        linked = subprocess.run(cc + [str(probe), '-lsqlite3', '-o', str(work / 'sqlite-provider')],
                                capture_output=True, timeout=30)
        if linked.returncode:
            print('SKIP CString SQLite exact buffer: sqlite3 provider cannot link: ' +
                  linked.stderr.decode(errors='replace').strip(), flush=True)
        else:
            run(work, 'sqlite-exact-buffer', SQLITE)
