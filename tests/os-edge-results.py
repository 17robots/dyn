#!/usr/bin/env python3
"""Linux terminal/native errors and openat2 capability result contracts."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use terminal "std/terminal"
use cap "std/fs/capability"
use bytes "std/bytes"
use io "std/io"
fn require(ok: bool) { if !ok { #panic("OS edge result contract") } }
// 1 NotFound, 2 InvalidInput, 3 another failure.
fn read_failure(directory: *const cap.Directory, path: []const u8, output: []u8) u8 {
 _ = cap.read(directory, path, output) catch err {
  case err {
   .NotFound => { return 1 }
   .InvalidInput => { return 2 }
   _ => { return 3 }
  }
 }
 #panic("capability read succeeded")
}
fn invalid(err: io.IoErr) bool {
 case err {
  .InvalidInput => { return true }
  _ => { return false }
 }
}
fn invalid_state(descriptor: isize) bool {
 _ = terminal.read_state(descriptor) catch err { return invalid(err) }
 return false
}
fn invalid_size(descriptor: isize) bool {
 _ = terminal.size(descriptor) catch err { return invalid(err) }
 return false
}
fn invalid_raw(descriptor: isize) bool {
 _ = terminal.raw(descriptor) catch err { return invalid(err) }
 return false
}
fn invalid_restore(descriptor: isize, saved: *const terminal.State) bool {
 terminal.restore(descriptor, saved) catch err { return invalid(err) }
 return false
}
fn main() {
 // A bad descriptor (EBADF) and a missing saved state are InvalidInput.
 require(invalid_state(-1) && invalid_size(-1) && invalid_raw(-1))
 saved := terminal.State{}
 require(invalid_restore(-1, &saved) && invalid_restore(-1, nil))
 require(!terminal.is_attached(-1))
 original := terminal.read_state(PTY_DESCRIPTOR) catch { #panic("read state") }
 changed := terminal.raw(PTY_DESCRIPTOR) catch { #panic("raw") }
 terminal.restore(PTY_DESCRIPTOR, &changed) catch { #panic("restore") }
 after := terminal.read_state(PTY_DESCRIPTOR) catch { #panic("read state") }
 require(bytes.equal(original.bytes[..], after.bytes[..]))
 output: [32]u8
 directory := cap.Directory{descriptor: DIRECTORY_DESCRIPTOR, active: true}
 count := cap.read(&directory, "ok", output[..]) catch { #panic("capability read") }
 require(count == 3 && bytes.equal(output[..3], "yes"))
 require(read_failure(&directory, "missing", output[..]) == 1)
 require(read_failure(&directory, "../secret", output[..]) != 0)
 require(read_failure(&directory, "link", output[..]) != 0)
 require(read_failure(nil, "ok", output[..]) == 2)
 zero := cap.Directory{}
 // EBADF.
 require(read_failure(&zero, "ok", output[..]) == 2)
}
'''

def main():
    if platform.system() != 'Linux':
        print('SKIP OS edge results: Linux required')
        return
    import pty
    with tempfile.TemporaryDirectory(prefix='dyn-os-edge-') as tmp:
        root = Path(tmp)
        (root / 'files').mkdir()
        (root / 'files/ok').write_bytes(b'yes')
        (root / 'secret').write_bytes(b'no')
        (root / 'files/link').symlink_to(root / 'secret')
        descriptor = os.open(root / 'files', os.O_RDONLY | os.O_DIRECTORY)
        master, slave = pty.openpty()
        try:
            (root / 'main.dyn').write_text(SOURCE.replace('PTY_DESCRIPTOR', str(slave)).replace('DIRECTORY_DESCRIPTOR', str(descriptor)))
            env = dict(os.environ, DYN_SDK=str(ROOT))
            for mode in ('debug', 'release'):
                output = root / ('test-' + mode)
                command = [DYN, 'build', str(root), '--no-cache', '--quiet', '--output', str(output)]
                if mode == 'release':
                    command.append('--release')
                subprocess.run(command, env=env, check=True, timeout=120)
                subprocess.run([str(output)], env=env, pass_fds=(descriptor, slave), check=True, timeout=10)
                print('PASS OS edge results ' + mode)
        finally:
            os.close(descriptor)
            os.close(master)
            os.close(slave)

if __name__ == '__main__':
    main()
