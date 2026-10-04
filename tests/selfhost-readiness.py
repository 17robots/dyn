#!/usr/bin/env python3
"""Exercise compiler-building primitives; this is not a self-host/bootstrap gate.

A small expression compiler scans runtime input, resolves symbols, recursively
parses precedence, and emits postfix bytecode. Its independent Python oracle
checks results and exact diagnostics in debug/release, including bounded output.
"""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
SOURCE = r'''use "std/bytes"
use "std/io"
use "std/mem"
use "std/process"
struct Symbol { name: []const u8, value: u8 }
struct Symbols { entries: [8]Symbol, count: usize }
struct Lookup { value: u8, ok: bool }
fn insert(table: *Symbols, name: []const u8, value: u8) bool {
  for i in 0..table.count { if bytes.equal(table.entries[i].name, name) { return false } }
  if table.count == 8 { return false }
  table.entries[table.count] = Symbol{ name: name, value: value }
  table.count += 1 return true
}
fn lookup(table: *const Symbols, name: []const u8) Lookup {
  for i in 0..table.count {
    if bytes.equal(table.entries[i].name, name) { return Lookup{ value: table.entries[i].value, ok: true } }
  }
  return Lookup{}
}
struct Compiler { source: []const u8, cursor: usize, code: [64]u8, used: usize, failed: bool, offset: usize }
fn fail(p: *Compiler, offset: usize) {
  if !p.failed { p.failed = true p.offset = offset }
}
fn space(p: *Compiler) {
  for p.cursor < #len(p.source) && p.source[p.cursor] == ' ' { p.cursor += 1 }
}
fn emit(p: *Compiler, value: u8) {
  if p.used == 64 { fail(p, p.cursor) return }
  p.code[p.used] = value p.used += 1
}
fn alpha(value: u8) bool { return value >= 'a' && value <= 'z' }
fn atom(p: *Compiler, symbols: *const Symbols, depth: usize) {
  space(p)
  start := p.cursor
  if depth > 16 || start == #len(p.source) { fail(p, start) return }
  value := p.source[start]
  if value >= '0' && value <= '9' { p.cursor += 1 emit(p, value) return }
  if alpha(value) {
    for p.cursor < #len(p.source) && alpha(p.source[p.cursor]) { p.cursor += 1 }
    found := lookup(symbols, p.source[start..p.cursor])
    if !found.ok { fail(p, start) return }
    emit(p, found.value) return
  }
  if value == '(' {
    p.cursor += 1 expression(p, symbols, depth + 1) space(p)
    if p.cursor == #len(p.source) || p.source[p.cursor] != ')' { fail(p, p.cursor) return }
    p.cursor += 1 return
  }
  fail(p, start)
}
fn product(p: *Compiler, symbols: *const Symbols, depth: usize) {
  atom(p, symbols, depth) space(p)
  for !p.failed && p.cursor < #len(p.source) && p.source[p.cursor] == '*' {
    p.cursor += 1 atom(p, symbols, depth) emit(p, '*') space(p)
  }
}
fn expression(p: *Compiler, symbols: *const Symbols, depth: usize) {
  product(p, symbols, depth) space(p)
  for !p.failed && p.cursor < #len(p.source) && p.source[p.cursor] == '+' {
    p.cursor += 1 product(p, symbols, depth) emit(p, '+') space(p)
  }
}
fn main() {
  storage: [16384]u8 = [] arena := mem.arena_from_buffer(storage[..])
  arguments := process.arguments(&arena)
  if !arguments.ok || #len(arguments.values) != 2 { #panic("arguments") }
  symbols := Symbols{}
  if !insert(&symbols, "alpha", '4') || !insert(&symbols, "beta", '7') { #panic("insert") }
  if insert(&symbols, "alpha", '8') || lookup(&symbols, "absent").ok { #panic("symbols") }
  for name in ["c", "d", "e", "f", "g", "h"] { if !insert(&symbols, name, '0') { #panic("capacity") } }
  if insert(&symbols, "full", '0') { #panic("overflow") }
  p := Compiler{ source: arguments.values[1] }
  expression(&p, &symbols, 0) space(&p)
  if p.cursor != #len(p.source) { fail(&p, p.cursor) }
  if p.failed { _ = io.println(io.stdout(), "error:{}", p.offset) }
  else { _ = io.println(io.stdout(), "{}", p.code[..p.used]) }
}
'''

# These exact bytecode expectations independently specify associativity and
# precedence. Malformed inputs must produce a stable original-source byte offset.
CASES = {
    'alpha + beta * 2': '472*+',
    '(alpha + beta) * 2': '47+2*',
    '9+8+7': '98+7+',
    '2*(3+(4*5))': '2345*+*',
    ' alpha ': '4',
    'unknown': 'error:0',
    'alpha + ': 'error:8',
    '(1+2': 'error:4',
    '1 2': 'error:2',
    '1+@': 'error:2',
    '': 'error:0',
    '(' * 18 + '1' + ')' * 18: 'error:17',
    '+'.join(['1'] * 34): 'error:65',
}
with tempfile.TemporaryDirectory(prefix='dyn-selfhost-primitives-') as directory:
    work = Path(directory)
    (work/'main.dyn').write_text(SOURCE)
    for release in (False, True):
        binary = work/('release' if release else 'debug')
        subprocess.run([DYN, 'build', str(work), '--no-cache', '--quiet', '--output', str(binary)] +
                       (['--release'] if release else []), check=True, timeout=90)
        for source, expected in CASES.items():
            result = subprocess.run([str(binary), source], capture_output=True, text=True, timeout=10)
            assert result.returncode == 0 and result.stdout == expected+'\n', (release, source, result.returncode, result.stdout, result.stderr)
print('PASS scanner, recursive parser, bounded symbols/emitter, source diagnostics: debug/release')
