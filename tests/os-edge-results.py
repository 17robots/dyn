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
use "std/fail"
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
fn main() {
 r: fail.Status
 _ = terminal.read_state(&r, -1)
 require(r.failed && r.failure.native == -9 && r.failure.kind == fail.Kind.InvalidState)
 s: fail.Status
 size := terminal.size(&s, -1)
 require(s.failed && s.failure.native == -9 && s.failure.kind == fail.Kind.InvalidState && size.rows == 0 && size.columns == 0)
 saved := terminal.State{}
 restored: fail.Status
 terminal.restore(&restored, -1, &saved)
 require(restored.failed && restored.failure.native == -9 && restored.failure.kind == fail.Kind.InvalidState)
 missing: fail.Status
 terminal.restore(&missing, -1, nil)
 require(missing.failed && missing.failure.native == 0 && missing.failure.kind == fail.Kind.InvalidInput)
 raw: fail.Status
 _ = terminal.raw(&raw, -1)
 require(raw.failed && raw.failure.native == -9 && raw.failure.kind == fail.Kind.InvalidState)
 require(!terminal.is_attached(-1))
 status: fail.Status
 original := terminal.read_state(&status, PTY_DESCRIPTOR)
 changed := terminal.raw(&status, PTY_DESCRIPTOR)
 terminal.restore(&status, PTY_DESCRIPTOR, &changed)
 after := terminal.read_state(&status, PTY_DESCRIPTOR)
 require(!status.failed && bytes.equal(original.bytes[..], after.bytes[..]))
 output: [32]u8
 directory := cap.Directory{descriptor: DIRECTORY_DESCRIPTOR, active: true}
 count := cap.read(&directory, "ok", output[..]) catch { #panic("capability read") }
 require(!status.failed && count == 3 && bytes.equal(output[..3], "yes"))
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
