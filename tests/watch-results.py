#!/usr/bin/env python3
"""Sticky watcher failures; Windows/macOS checks are cross-links, not execution."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
PORTABLE = '''use watch "std/fs/watch"
use io "std/io"
fn require(ok: bool) { if !ok { #panic("watch result contract") } }
// The system code for System, 1 for InvalidInput, 2 for anything else.
fn code(err: io.IoErr) isize {
 case err {
  .System(native) => { return native }
  .InvalidInput => { return 1 }
  _ => { return 2 }
 }
}
fn next_failure(state: *watch.Watcher) isize {
 _ = watch.next(state) catch err {
  require(state.ended)
  return code(err)
 }
 #panic("watch.next succeeded")
}
fn main() {
 state := watch.Watcher{}
 first := next_failure(&state)
 require(first == 1)
 for i in 0..3 {
  next := next_failure(&state)
  require(next == first)
 }
 watch.close(&state)
 again := next_failure(&state)
 require(again == first)
}
'''
LINUX = '''use watch "std/fs/watch"
use io "std/io"
fn require(ok: bool) { if !ok { #panic("watch read after failure") } }
// The system code for System, 1 for InvalidInput, 2 for anything else.
fn code(err: io.IoErr) isize {
 case err {
  .System(native) => { return native }
  .InvalidInput => { return 1 }
  _ => { return 2 }
 }
}
fn next_failure(state: *watch.Watcher) isize {
 _ = watch.next(state) catch err {
  require(state.ended)
  return code(err)
 }
 #panic("watch.next succeeded")
}
fn main() {
 backing: [272]u8
 state := watch.Watcher{descriptor: 999999, active: true, storage: backing[..]}
 first := next_failure(&state)
 require(first == 1)
 descriptors: [2]i32
 require(#syscall(293, &descriptors[0], 2048) == 0)
 defer { _ = #syscall(3, descriptors[0])
 _ = #syscall(3, descriptors[1]) }
 byte: [1]u8 = [91]
 require(#syscall(1, descriptors[1], &byte[0], 1) == 1)
 state.descriptor = #cast(isize, descriptors[0])
 for i in 0..3 {
  result := next_failure(&state)
  require(result == first && state.used == 0)
 }
 byte[0] = 0
 require(#syscall(0, descriptors[0], &byte[0], 1) == 1 && byte[0] == 91)
 state = watch.Watcher{storage: backing[..], used: 273}
 malformed := next_failure(&state)
 require(malformed == -74)
 state.used = 0
 repeated := next_failure(&state)
 require(repeated == -74)
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
