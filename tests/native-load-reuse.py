#!/usr/bin/env python3
"""Repeated loads must observe overlapping stores, calls, copies and loop writes."""
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
SOURCE = '''use "std/io"
struct Pair { a: u64, b: u64 }
fn repeat(p: *const u64) u64 { a := p.*
b := p.*
return a + b }
fn store(p: *const u64, q: *u64) u64 {
  a := p.*
  q.* = 41
  return a * 100 + p.*
}
fn mutate(p: *u64) { p.* = 23 }
fn call(p: *u64) u64 { a := p.*
mutate(p)
return a * 100 + p.* }
fn narrow(p: *u64) u64 {
  a := p.*
  byte := #cast(*u8, p)
  byte.* = 9
  return a * 100 + p.*
}
fn copy(p: *Pair, q: *const Pair) u64 {
  a := p.a
  p.* = q.*
  return a * 100 + p.a
}
fn clear(p: *Pair) u64 { a := p.a
p.* = Pair{}
return a * 100 + p.a }
fn loop(p: *u64) u64 {
  total: u64 = 0
  for i in 0..8 { total += p.*
  p.* += 1 }
  return total
}
fn branch(p: *u64, change: bool) u64 {
  a := p.*
  if change { p.* = 37 }
  return a * 100 + p.*
}
fn main() {
  for i in 1..33 {
    value := #cast(u64, i)
    if repeat(&value) != value * 2 { #panic("repeat") }
    if store(&value, &value) != (#cast(u64, i)) * 100 + 41 { #panic("store alias") }
    value = #cast(u64, i)
    if call(&value) != (#cast(u64, i)) * 100 + 23 { #panic("call barrier") }
    value = #cast(u64, i)
    if narrow(&value) != (#cast(u64, i)) * 100 + 9 { #panic("partial store") }
    data: [4]u64 = [11, 13, 17, 19]
    p := #cast(*Pair, &data[1])
    q := #cast(*const Pair, &data[0])
    if copy(p, q) != 1311 || p.a != 11 || p.b != 13 { #panic("overlap copy") }
    if clear(p) != 1100 || p.a != 0 || p.b != 0 { #panic("zero barrier") }
    value = 1
    if loop(&value) != 36 || value != 9 { #panic("loop writes") }
    value = 5
    if branch(&value, false) != 505 { #panic("branch read") }
    if branch(&value, true) != 537 { #panic("branch store") }
  }
  _ = io.println(io.stdout(), "load reuse passed")
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-load-reuse-') as temporary:
    work = Path(temporary)
    source = work/'src'
    source.mkdir()
    (source/'main.dyn').write_text(SOURCE)
    for mode in ('debug', 'release'):
        for level in ((2, 3) if mode == 'release' else (2,)):
            for tree in ('0', '1'):
                output = work/f'{mode}-{level}-{tree}'
                env = dict(os.environ, DYN_NO_SSA=tree)
                command = [DYN, 'build', str(source), '--'+mode, '--no-cache',
                           '--output', str(output)]
                if mode == 'release':
                    command += ['--opt-level', str(level)]
                built = subprocess.run(command, env=env, capture_output=True, text=True, timeout=90)
                assert built.returncode == 0, built.stderr
                ran = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
                assert ran.returncode == 0 and ran.stdout == 'load reuse passed\n', ran
                if (mode == 'release' and level == 2 and tree == '0' and
                        platform.system() == 'Linux' and platform.machine() == 'x86_64' and
                        shutil.which('objdump')):
                    assembly = subprocess.check_output(
                        ['objdump', '-d', '--no-show-raw-insn', str(output)], text=True)
                    body = assembly.split('<repeat>:\n')[1].split('\n\n')[0]
                    reads = re.findall(r'\b(?:mov\w*|add\w*)\s+[^,\n]*\([^\)\n]*\),%', body)
                    assert len(reads) == 1, ('repeated pointer load was not reused', body)
print('PASS repeated loads: aliasing stores, partial writes, calls, overlap copies, zeroing, loops and branches')
