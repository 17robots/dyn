#!/usr/bin/env python3
"""dyn vet warns when a struct is copied with = and both copies are passed by
mutable pointer to the same function (fs.close(&file), fs.close(&copy)),
without knowing any function or type by name. Read-only (*const) calls and a
copy passed alone are not reported; the compiler itself accepts the code."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/fs"
use "std/io"
use "std/net"

struct Pool { size: i32 }

fn release(pool: *Pool) {
  pool.size = 0
}

fn grow(pool: *Pool) {
  pool.size += 1
}

fn main() {
  opened := fs.open("main.dyn")
  if io.failed(opened.failure) { return }
  file := opened.value
  copy := file
  _ = fs.is_open(&file)
  _ = fs.is_open(&copy)
  fs.close(&file)
  fs.close(&copy)
  listener := net.Listener{}
  other := listener
  net.listener_close(&other)
  net.listener_close(&listener)
  first := Pool{}
  second := first
  release(&first)
  release(&second)
  alone := Pool{}
  spare := alone
  grow(&alone)
  _ = spare
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-vet-copied-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    vetted = subprocess.run([DYN, 'vet', str(project)], capture_output=True, text=True, timeout=60)
    warnings = [line for line in vetted.stderr.splitlines() if 'is a copy of' in line]
    assert vetted.returncode == 1 and len(warnings) == 3, vetted.stderr
    assert "main.dyn:23:" in warnings[0] and "'copy' is a copy of 'file', and both are passed to close" in warnings[0], warnings
    assert "'other' is a copy of 'listener', and both are passed to listener_close" in warnings[1], warnings
    assert "'second' is a copy of 'first', and both are passed to release" in warnings[2], warnings
    checked = subprocess.run([DYN, 'check', str(project)], capture_output=True, text=True, timeout=60)
    assert checked.returncode == 0, checked.stderr
print('PASS vet copied handles: copies passed to one function, by shape, not by name')
