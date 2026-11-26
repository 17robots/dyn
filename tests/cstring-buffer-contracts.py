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

SOURCE = r'''use c "std/c"
use io "std/io"
use mem "std/mem"
use fs "std/fs"
fn check(ok:bool) { if !ok { #panic("CString buffer contract") } }
// The kinds of failure these fixtures meet; Ok when a call worked.
enum Kind { Ok, NotFound, PermissionDenied, AlreadyExists, InvalidInput, WouldBlock, Interrupted, Unsupported, Capacity, System }
fn kind_of(err: io.IoErr) Kind {
 case err {
  .NotFound => { return Kind.NotFound }
  .PermissionDenied => { return Kind.PermissionDenied }
  .AlreadyExists => { return Kind.AlreadyExists }
  .InvalidInput => { return Kind.InvalidInput }
  .WouldBlock => { return Kind.WouldBlock }
  .Interrupted => { return Kind.Interrupted }
  .Unsupported => { return Kind.Unsupported }
  .Capacity => { return Kind.Capacity }
  .System => { return Kind.System }
 }
}
fn kind(destination:[]u8, source:[]const u8) Kind {
 _ = c.string_into(destination,source) catch err { return kind_of(err) }
 return Kind.Ok
}
fn main() {
 backing:[6]u8
 mem.fill(backing[..],165)
 exact:=c.string_into(backing[1..5],"abc") catch { #panic("exact") }
 check(exact==&backing[1])
 check(mem.equal(backing[1..5],"abc\x00") && backing[0]==165 && backing[5]==165)
 empty:=c.string_into(backing[1..2],"") catch { #panic("empty") }
 check(empty==&backing[1] && backing[1]==0)
 check(backing[0]==165 && backing[2]=='b' && backing[5]==165)
 mem.fill(backing[..],165)
 check(kind(backing[1..4],"abc") == Kind.Capacity)
 check(kind(backing[..0],"") == Kind.Capacity)
 check(kind(backing[..],"a\x00b") == Kind.InvalidInput)
 for byte in backing { check(byte==165) }
 _=mem.copy(backing[..],"abcde!")
 overlap:=c.string_into(backing[1..5],backing[..3]) catch { #panic("overlap") }
 check(overlap==&backing[1] && mem.equal(backing[..],"aabc\x00!"))
 reverse:=c.string_into(backing[..4],backing[1..4]) catch { #panic("reverse") }
 check(reverse==&backing[0] && mem.equal(backing[..],"abc\x00\x00!"))
 before:[6]u8
 _=mem.copy(before[..],backing[..])
 check(kind(backing[1..],backing[..5]) == Kind.InvalidInput && mem.equal(backing[..],before[..]))
 huge:=#slice(&backing[0], ~#cast(usize,0))
 check(kind(backing[..],huge) == Kind.InvalidInput && mem.equal(backing[..],before[..]))
 path:[4300]u8
 mem.fill(path[..],'a')
 removed := false
 fs.remove(path[..]) catch { removed = true }
 check(removed)
 for byte in path { check(byte=='a') }
}
'''
SQLITE = r'''use sqlite "vendor/sqlite"
fn main() {
 backing:[11]u8
 for *byte in backing { byte.*=165 }
 database:=sqlite.open(":memory:",backing[1..10]) catch { #panic("SQLite exact CString buffer") }
 if database==nil { #panic("SQLite exact CString buffer") }
 if backing[0]!=165 || backing[10]!=165 { #panic("SQLite CString canaries") }
 sqlite.close(database) catch { #panic("SQLite close") }
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
    gl = '''use gl "vendor/opengl"
use c "std/c"
use mem "std/mem"
const names:[COUNT][]const u8=[NAMES]
visited:usize=0
fail_second:bool=false
fn loader(name:*const u8) rawptr {
 text:=c.bytes_from_string(name,64) catch { #panic("OpenGL CString loader") }
 if visited>=names.len || !mem.equal(text,names[visited]) { #panic("OpenGL CString loader") }
 visited+=1
 if fail_second && visited==2 { return nil }
 return #cast(rawptr,1)
}
fn load_fails(proc: fn(*const u8) rawptr) bool {
 _=gl.load(proc) catch { return true }
 return false
}
fn main() {
 if !load_fails(nil) || visited!=0 { #panic("nil loader") }
 if load_fails(loader) || visited!=names.len { #panic("OpenGL complete table") }
 visited=0
 fail_second=true
 if !load_fails(loader) || visited!=2 { #panic("OpenGL missing symbol") }
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
