#!/usr/bin/env python3
"""Exact store forwarding preserves memory effects, representations and checks."""
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
def payload_reads(body):
    # A global address can arrive through a GOT load or a RIP-relative LEA.
    # Recognize a GOT address load only when the next instruction stores
    # through that destination register. RIP-relative payload loads still count.
    instructions = [line.split('\t')[-1].split('#')[0].strip()
                    for line in body.splitlines() if '\t' in line]
    reads = []
    for index, instruction in enumerate(instructions):
        load = re.match(r'(?:mov\w*|add\w*)\s+([^,]+),(%\w+)$', instruction)
        if not load or '(' not in load[1]:
            continue
        address_load = False
        if '%rip' in load[1] and index + 1 < len(instructions):
            following = instructions[index + 1]
            address_load = bool(re.match(
                r'mov\w*\s+%\w+,\(' + re.escape(load[2]) + r'\)$', following))
        if not address_load:
            reads.append(instruction)
    return reads

# Negative control: direct global payload reads must not disappear merely
# because their addressing mode uses RIP. LEA computes an address without a read.
assert payload_reads('0:\tmov %rdi,0x10(%rip)\n1:\tmov 0x10(%rip),%rax')
assert not payload_reads('0:\tlea 0x10(%rip),%rax\n1:\tmov %rdi,(%rax)')
assert not payload_reads('0:\tmov 0x10(%rip),%rax\n1:\tmov %rdi,(%rax)')

SOURCE = '''use "std/io"
global: u64 = 0
calls: u64 = 0
struct Pair { a: u64, b: u64 }
pub fn exact(v: u64) u64 { global = v return global }
pub fn floating(p: *f64, v: f64) f64 { p.* = v return p.* }
pub fn floating32(p: *f32, v: f32) f32 { p.* = v return p.* }
pub fn alias(p: *u64, q: *u64, v: u64) u64 { p.* = v q.* = 29 return p.* }
pub fn mutate(p: *u64) { p.* = 31 }
pub fn barrier(p: *u64, v: u64) u64 { p.* = v mutate(p) return p.* }
pub fn copy(p: *Pair, q: *const Pair) u64 { p.a = 43 p.* = q.* return p.a }
pub fn clear(p: *Pair) u64 { p.a = 43 p.* = Pair{} return p.a }
pub fn offset(p: *Pair, v: u64) u64 { p.a = v return p.b }
pub fn narrow(p: *u8, v: u64) u64 { p.* = #cast(u8, v) return #cast(u64, p.*) }
pub fn signed(p: *i8, v: i64) i64 { p.* = #cast(i8, v) return #cast(i64, p.*) }
pub fn bits(p: *f64, v: f64) u64 { p.* = v return #cast(*u64, p).* }
pub fn partial(p: *u64, v: u64) u64 { p.* = v #cast(*u8, p).* = 9 return p.* }
pub fn once(v: u64) u64 { calls += 1 return v }
pub fn checked(p: *u64, v: u64, d: u64) u64 { p.* = once(v) q := p.* / d return q }
cb_exact: fn(u64) u64 = &exact
cb_floating: fn(*f64, f64) f64 = &floating
cb_floating32: fn(*f32, f32) f32 = &floating32
cb_alias: fn(*u64, *u64, u64) u64 = &alias
cb_barrier: fn(*u64, u64) u64 = &barrier
cb_copy: fn(*Pair, *const Pair) u64 = &copy
cb_clear: fn(*Pair) u64 = &clear
cb_offset: fn(*Pair, u64) u64 = &offset
cb_narrow: fn(*u8, u64) u64 = &narrow
cb_signed: fn(*i8, i64) i64 = &signed
cb_bits: fn(*f64, f64) u64 = &bits
cb_partial: fn(*u64, u64) u64 = &partial
cb_checked: fn(*u64, u64, u64) u64 = &checked
fn main() {
  for i in 1..33 {
    v := #cast(u64, i)
    if cb_exact(v) != v || global != v { #panic("global") }
    x: u64 = 0
    if cb_alias(&x, &x, v) != 29 || cb_barrier(&x, v) != 31 { #panic("barriers") }
    a := Pair{} b := Pair{a: 17, b: 19}
    if cb_copy(&a, &b) != 17 { #panic("copy") }
    if cb_offset(&a, v) != 19 || cb_clear(&a) != 0 { #panic("offset or zero") }
    byte: u8 = 0 signedbyte: i8 = 0
    if cb_narrow(&byte, 511) != 255 || cb_signed(&signedbyte, -1) != -1 { #panic("narrow") }
    if cb_partial(&x, 256) != 265 { #panic("partial") }
    if cb_checked(&x, v, 1) != v || x != v { #panic("checked") }
  }
  if calls != 32 { #panic("evaluate once") }
  raw: [5]u64 = [0, 9223372036854775808, 9221120237041095220, 18444492273895871028, 9218868437227405313]
  for r in raw {
    f: f64 = 0.0
    v := #bitcast(f64, r)
    if #bitcast(u64, cb_floating(&f, v)) != r || #bitcast(u64, f) != r || cb_bits(&f, v) != r { #panic("float bits") }
  }
  raw32: [4]u32 = [0, 2147483648, 2143294004, 4286583348]
  for r in raw32 {
    f: f32 = 0.0
    if #bitcast(u32, cb_floating32(&f, #bitcast(f32, r))) != r { #panic("float32 bits") }
  }
  _ = io.println(io.stdout(), "store forwarding passed")
}
'''
PANIC = '''global: u64 = 0
pub fn guarded(d: u64) u64 { global = 41 q := global / d return q }
fn main() { _ = guarded(0) }
'''

with tempfile.TemporaryDirectory(prefix='dyn-store-forward-') as temporary:
    work = Path(temporary)
    source = work/'src'
    source.mkdir()
    (source/'main.dyn').write_text(SOURCE)
    for mode in ('debug', 'release'):
        for level in ((2, 3) if mode == 'release' else (2,)):
            for tree in ('0', '1'):
                output = work/f'{mode}-{level}-{tree}'
                env = dict(os.environ, DYN_NO_SSA=tree)
                command = [DYN, 'build', str(source), '--'+mode, '--no-cache', '--output', str(output)]
                if mode == 'release':
                    command += ['--opt-level', str(level)]
                built = subprocess.run(command, env=env, capture_output=True, text=True, timeout=90)
                assert built.returncode == 0, built.stderr
                ran = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
                assert ran.returncode == 0 and ran.stdout == 'store forwarding passed\n', ran
                if (mode == 'release' and level == 2 and tree == '0' and
                        platform.system() == 'Linux' and platform.machine() == 'x86_64' and shutil.which('objdump')):
                    assembly = subprocess.check_output(['objdump', '-d', '--no-show-raw-insn', str(output)], text=True)
                    for symbol in ('exact', 'floating'):
                        body = assembly.split('<'+symbol+'>:\n')[1].split('\n\n')[0]
                        reads = payload_reads(body)
                        assert not reads, ('store result reloaded', symbol, body)
    (source/'main.dyn').write_text(PANIC)
    results = []
    for tree in ('0', '1'):
        output = work/('panic-'+tree)
        built = subprocess.run([DYN, 'build', str(source), '--release', '--opt-level', '2', '--no-cache', '--output', str(output)], env=dict(os.environ, DYN_NO_SSA=tree), capture_output=True, text=True, timeout=90)
        assert built.returncode == 0, built.stderr
        ran = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
        assert ran.returncode != 0, ran
        results.append((ran.returncode, ran.stdout, ran.stderr))
    assert results[0] == results[1], results
print('PASS exact store forwarding: globals, aliases, calls, copies, widths, raw float bits, guards and evaluate once')
