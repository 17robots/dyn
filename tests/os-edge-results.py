#!/usr/bin/env python3
"""Linux terminal/native errors and openat2 capability result contracts."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/terminal" terminal
use "std/fs/capability" cap
use "std/errors" errors
use "std/bytes" bytes
fn require(ok: bool) { if !ok { #panic("OS edge result contract") } }
fn main() {
 r := terminal.read_state(-1)
 require(!r.ok && r.error == -9 && r.kind == errors.Kind.InvalidState)
 s := terminal.size(-1)
 require(!s.ok && s.error == -9 && s.kind == errors.Kind.InvalidState && s.rows == 0 && s.columns == 0)
 saved := terminal.State{}
 restored := terminal.restore(-1, &saved)
 require(!restored.ok && restored.error == -9 && restored.kind == errors.Kind.InvalidState)
 restored = terminal.restore(-1, nil)
 require(!restored.ok && restored.error == 0 && restored.kind == errors.Kind.InvalidInput)
 r = terminal.raw(-1)
 require(!r.ok && r.error == -9 && r.kind == errors.Kind.InvalidState)
 require(!terminal.is_attached(-1))
 r = terminal.read_state(PTY_DESCRIPTOR)
 require(r.ok && r.error == 0 && r.kind == errors.Kind.None)
 changed := terminal.raw(PTY_DESCRIPTOR)
 require(changed.ok && changed.error == 0 && changed.kind == errors.Kind.None)
 require(terminal.restore(PTY_DESCRIPTOR, &changed.value).ok)
 after := terminal.read_state(PTY_DESCRIPTOR)
 require(after.ok && bytes.equal(r.value.bytes[..], after.value.bytes[..]))
 output: [32]u8 = []
 directory := cap.Directory{descriptor: DIRECTORY_DESCRIPTOR}
 read := cap.read(&directory, "ok", output[..])
 require(read.ok && read.value == 3 && read.error == 0 && read.kind == errors.Kind.None && bytes.equal(output[..3], "yes"))
 read = cap.read(&directory, "missing", output[..])
 require(!read.ok && read.value == 0 && read.error == -2 && read.kind == errors.Kind.NotFound)
 read = cap.read(&directory, "../secret", output[..])
 require(!read.ok && read.value == 0 && read.error < 0 && read.kind != errors.Kind.None)
 read = cap.read(&directory, "link", output[..])
 require(!read.ok && read.value == 0 && read.error < 0 && read.kind != errors.Kind.None)
 read = cap.read(nil, "ok", output[..])
 require(!read.ok && read.error == -22 && read.kind == errors.Kind.InvalidInput)
 zero := cap.Directory{}
 read = cap.read(&zero, "ok", output[..])
 require(!read.ok && read.error == -9 && read.kind == errors.Kind.InvalidState)
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
