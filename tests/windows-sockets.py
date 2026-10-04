#!/usr/bin/env python3
"""Build Windows socket initialization contracts; execute on native Windows."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build' / ('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve()
COMMON = '''use "std/os/windows" win
fn sockets() {
  for i in 0..32 {
    opened := win.socket_open(2, 1, 6)
    if !opened.ok { #panic("socket_open without explicit WSAStartup") }
    if !win.socket_close(#cast(usize) opened.value) { #panic("socket_close") }
  }
  invalid := win.socket_open(-1, 1, 0)
  if invalid.ok || invalid.error == 0 || invalid.error == 10093 || invalid.value != -1 {
    #panic("native socket error lost or Winsock uninitialized")
  }
}
'''
CASES = {
    'first-open': COMMON + 'fn main() { sockets() }\n',
    'concurrent-first-open': COMMON + '''
use "std/sync" sync
ready: sync.AtomicU32 = sync.AtomicU32{}
start: sync.AtomicU32 = sync.AtomicU32{}
fn worker(context: rawptr) isize {
  _ = context
  _ = sync.fetch_add_u32(&ready, 1)
  for sync.fetch_add_u32(&start, 0) == 0 { win.thread_yield() }
  sockets()
  return 0
}
fn main() {
  threads: [8]win.Thread = []
  for i in 0..8 {
    if !win.thread_spawn(&threads[i], 65536, &worker, nil) { #panic("spawn") }
  }
  for sync.fetch_add_u32(&ready, 0) != 8 { win.thread_yield() }
  _ = sync.exchange_u32(&start, 1)
  for i in 0..8 {
    if !win.thread_join(&threads[i]) { #panic("join") }
  }
  sockets()
}
''',
}

with tempfile.TemporaryDirectory(prefix='dyn-windows-sockets-') as temporary:
    for name, source in CASES.items():
        project = Path(temporary) / name
        project.mkdir()
        (project / 'main.dyn').write_text(source)
        for mode in ('--debug', '--release'):
            output = project / 'program.exe'
            subprocess.run([str(DYN), 'build', str(project), '--target', 'x86_64-windows',
                            mode, '--no-cache', '--quiet', '--output', str(output)],
                           check=True, timeout=90)
            if os.name == 'nt':
                subprocess.run([str(output)], check=True, timeout=20)
if os.name == 'nt':
    print('PASS Windows socket first use, concurrent initialization, repeated open/close, and native errors (debug/release)')
else:
    print('PASS Windows socket contracts cross-build/link (debug/release); native execution not covered on this host')
