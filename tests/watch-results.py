#!/usr/bin/env python3
"""Sticky watcher failures; Windows/macOS checks are cross-links, not execution."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
PORTABLE = '''use "std/fs/watch" watch
use "std/fail"
fn require(ok: bool) { if !ok { #panic("watch result contract") } }
fn next_failure(state: *watch.Watcher) fail.Failure {
 status: fail.Status
 _ = watch.next(&status, state)
 require(status.failed && state.ended)
 return status.failure
}
fn main() {
 state := watch.Watcher{}
 first := next_failure(&state)
 require(first.native == -9 && first.kind == fail.Kind.InvalidState)
 for i in 0..3 {
  next := next_failure(&state)
  require(next.native == first.native && next.kind == first.kind)
 }
 watch.close(&state)
 again := next_failure(&state)
 require(again.native == first.native && again.kind == first.kind)
}
'''
LINUX = '''use "std/fs/watch" watch
use "std/fail"
fn require(ok: bool) { if !ok { #panic("watch read after failure") } }
fn next_failure(state: *watch.Watcher) fail.Failure {
 status: fail.Status
 _ = watch.next(&status, state)
 require(status.failed && state.ended)
 return status.failure
}
fn main() {
 backing: [272]u8
 state := watch.Watcher{descriptor: 999999, active: true, storage: backing[..]}
 first := next_failure(&state)
 require(first.native == -9 && first.kind == fail.Kind.InvalidState)
 descriptors: [2]i32
 require(#syscall(293, &descriptors[0], 2048) == 0)
 defer { _ = #syscall(3, descriptors[0])
 _ = #syscall(3, descriptors[1]) }
 byte: [1]u8 = [91]
 require(#syscall(1, descriptors[1], &byte[0], 1) == 1)
 state.descriptor = #cast(isize, descriptors[0])
 for i in 0..3 {
  result := next_failure(&state)
  require(result.native == first.native && result.kind == first.kind && state.used == 0)
 }
 byte[0] = 0
 require(#syscall(0, descriptors[0], &byte[0], 1) == 1 && byte[0] == 91)
 state = watch.Watcher{storage: backing[..], used: 273}
 malformed := next_failure(&state)
 require(malformed.native == -74 && malformed.kind == fail.Kind.System)
 state.used = 0
 repeated := next_failure(&state)
 require(repeated.native == -74 && repeated.kind == malformed.kind)
}
'''

def main():
    env = dict(os.environ, DYN_SDK=str(ROOT))
    with tempfile.TemporaryDirectory(prefix='dyn-watch-results-') as tmp:
        root = Path(tmp)
        for target in (None, 'x86_64-windows', 'aarch64-macos'):
            for mode in ('debug', 'release'):
                (root/'main.dyn').write_text(PORTABLE)
                output=root/'probe'
                command=[DYN,'build',str(root),'--quiet','--no-cache','--output',str(output),'--'+mode]
                if target:
                    command += ['--target',target]
                subprocess.run(command,env=env,check=True,timeout=120)
                if target is None:
                    subprocess.run([str(output)],check=True,timeout=10)
                print('PASS watcher results',target or 'host',mode, '(cross-link only)' if target else '')
        if platform.system() == 'Linux':
            (root/'main.dyn').write_text(LINUX)
            for mode in ('debug','release'):
                subprocess.run([DYN,'build',str(root),'--quiet','--no-cache','--output',str(root/'read'),'--'+mode],env=env,check=True,timeout=120)
                subprocess.run([str(root/'read')],check=True,timeout=10)
                print('PASS watcher no read after failure',mode)
if __name__=='__main__':
    main()
