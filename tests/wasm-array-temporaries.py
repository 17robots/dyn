#!/usr/bin/env python3
"""Large and mixed aggregate initializers must not consume one Wasm local per item."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
NODE = os.environ.get('NODE', 'node')
if not shutil.which(NODE):
    print('SKIP Wasm array temporaries: Node unavailable')
    raise SystemExit(0)

SOURCE = r'''struct Defaults { floating: f64 = 1.5, integer: i64 = 9007199254740993, narrow: f32 = -4.25, bytes: [2]u32 = [7, 8] }
struct Mixed { floating: f64, integer: i64, narrow: f32, bytes: [2]u32 }
sequence: i32 = 0
fn effect(value: i32) i32 {
  sequence = sequence * 10 + value
  return value
}
initial: [3]i32 = [effect(1), effect(2), effect(3)]
fn combine(prefix: f64, values: [2]Mixed, suffix: i64) f64 {
  if prefix != 42.5 || suffix != -9 { #panic("outer arguments overwritten") }
  if values[0].integer != 9007199254740993 || values[1].integer != -9007199254740993 { #panic("i64 initializer type") }
  if values[0].floating != 1.25 || values[1].floating != -2.5 || values[0].narrow != 3.5 || values[1].narrow != -4.25 { #panic("float initializer types") }
  if values[0].bytes[0] != 4 || values[0].bytes[1] != 5 || values[1].bytes[0] != 6 || values[1].bytes[1] != 7 { #panic("nested evaluation order") }
  return prefix + values[0].floating + values[1].floating + #cast(f64, suffix)
}
fn main() {
  if sequence != 123 || initial[0] != 1 || initial[2] != 3 { #panic("global effect order") }
  for i in 0..30000 { if table[i] != #cast(u32, i) { #panic("large global initializer") } }
  sequence = 0
  result := combine(42.5, [Mixed{ floating: 1.25, integer: 9007199254740993, narrow: 3.5, bytes: [#cast(u32, effect(4)), #cast(u32, effect(5))] }, Mixed{ floating: -2.5, integer: -9007199254740993, narrow: -4.25, bytes: [#cast(u32, effect(6)), #cast(u32, effect(7))] }], -9)
  if result != 32.25 || sequence != 4567 { #panic("nested aggregate result") }
  // Aggregate elements can contain pointers/slices to stack slots: reusing a
  // local register must never rewind the actual aggregate backing storage.
  first: [2]u32 = [10, 11]
  second: [2]u32 = [20, 21]
  views: [2][]u32 = [first[..], second[..]]
  views[0][1] = 99
  if first[1] != 99 || views[1][0] != 20 { #panic("slice storage lifetime") }
  defaults: [2]Defaults = [Defaults{}, Defaults{ floating: 7.5 }]
  if defaults[0].floating != 1.5 || defaults[1].floating != 7.5 || defaults[1].integer != 9007199254740993 || defaults[0].narrow != -4.25 || defaults[1].bytes[1] != 8 { #panic("mixed default fields") }
  local: [4]f64 = [1.5, 2.5, 3.5, 4.5]
  if local[0] + local[3] != 6.0 { #panic("local floating array") }
}
'''
WASI = "const {WASI}=require('node:wasi'),fs=require('node:fs');(async()=>{const wasi=new WASI({version:'preview1',returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});"


def leb(data, at):
    value = 0
    shift = 0
    while True:
        byte = data[at]
        at += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, at
        shift += 7


def maximum_locals(data):
    at = 8
    maximum = 0
    while at < len(data):
        section = data[at]
        size, start = leb(data, at + 1)
        end = start + size
        if section == 10:
            count, cursor = leb(data, start)
            for _ in range(count):
                body_size, body_start = leb(data, cursor)
                groups, entry = leb(data, body_start)
                total = 0
                for _ in range(groups):
                    amount, entry = leb(data, entry)
                    total += amount
                    entry += 1  # Physical Wasm value type.
                maximum = max(maximum, total)
                cursor = body_start + body_size
        at = end
    return maximum


with tempfile.TemporaryDirectory(prefix='dyn-wasm-array-temporaries-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text('table: [30000]u32 = [' + ','.join(map(str, range(30000))) + ']\n' + SOURCE)
    for flags in (['--debug'], ['--release'], ['--release', '--opt-level', '3']):
        output = work / 'program.wasm'
        subprocess.run([DYN, 'build', str(work), '--target', 'wasm32-wasi', *flags, '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=300)
        subprocess.run([NODE, '--no-warnings', '-e', WASI, str(output)], check=True, timeout=60)
        assert maximum_locals(output.read_bytes()) < 4096, 'array-size-dependent Wasm local declarations'
print('PASS Wasm array temporaries: 30k global values, typed nested aggregates, outer arguments, side effects and slice backing (debug/O2/O3)')
