#!/usr/bin/env python3
"""Structs and plain enums print their contents at run time through
#typeof on an any, from any expression, on every backend; dyn vet reports a
literal template whose {} count differs from its values."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/fail"
use "std/fmt"
use "std/html"
use "std/io"
use "std/strings"
use "std/mem"

struct Vec2 { x: f64, y: f64 }
enum Op { Add, Sub }
enum Code { None = 0, Ok = 200, Missing = 404 }
enum Shape { Dot, Circle(f64) }
struct Unit { name: []const u8, at: Vec2, op: Op, code: Code, hp: i32, alive: bool, size: u8 }

fn spot() Unit {
  return Unit{ name: "bo", op: Op.Add }
}

fn main() {
  arena := mem.arena_alloc(0)
  defer mem.arena_release(arena)
  units: [2]Unit = [spot(), Unit{ name: "ada", at: Vec2{ x: 1.5, y: 2.0 }, op: Op.Sub, code: Code.Missing, hp: -7, alive: true, size: 3 }]
  io.println("{}", units[1])
  io.println("{} {}", spot(), Op.Sub)
  io.println("{}", Shape.Circle(1.0))
  storage: [256]u8
  buffer_status: fail.Status
  buffer := fmt.buffer(&buffer_status, storage[..])
  fmt.print(&buffer, "[{}]", units[1].at)
  io.println("{} {}", fmt.bytes(&buffer), strings.format(arena, "{}", Code.Ok))
  page_storage: [256]u8
  page_status: fail.Status
  page := html.writer(&page_status, page_storage[..])
  html.print(&page, "<p>{}</p>", Unit{ name: "<b>&" })
  io.println("{}", html.output(&page).bytes)
}
'''
EXPECTED = ('Unit{name: ada, at: Vec2{x: 1.5, y: 2}, op: Sub, code: Missing, hp: -7, alive: true, size: 3}\n'
            'Unit{name: bo, at: Vec2{x: 0, y: 0}, op: Add, code: None, hp: 0, alive: false, size: 0} Sub\n'
            '{?}\n'
            '[Vec2{x: 1.5, y: 2}] Ok\n'
            '<p>Unit{name: &lt;b&gt;&amp;, at: Vec2{x: 0, y: 0}, op: Add, code: None, hp: 0, alive: false, size: 0}</p>\n')
WASI = r'''
const {WASI}=require('node:wasi'),fs=require('fs');
(async()=>{const wasi=new WASI({version:'preview1',args:['test'],returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});
'''
with tempfile.TemporaryDirectory(prefix='dyn-print-structs-') as temporary:
    work = Path(temporary)
    (work / 'ok').mkdir()
    (work / 'ok' / 'main.dyn').write_text(SOURCE)
    for name, flags, env, emulator in (
            ('debug', ['--debug'], {}, []), ('release', ['--release'], {}, []),
            ('tree', ['--release'], {'DYN_NO_SSA': '1'}, []),
            ('arm', ['--target', 'aarch64-linux', '--release'], {}, ['qemu-aarch64']),
            ('wasi.wasm', ['--target', 'wasm32-wasi'], {}, ['node', '--no-warnings', '-e', WASI])):
        program = work / name
        subprocess.run([DYN, 'build', str(work / 'ok'), *flags, '--quiet', '--no-cache', '--output', str(program)],
                       check=True, timeout=180, env={**os.environ, **env})
        if emulator and not shutil.which(emulator[0]):
            continue
        result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0 and result.stdout == EXPECTED, (name, result)
    (work / 'bad').mkdir()
    (work / 'bad' / 'main.dyn').write_text('use "std/io"\n\nfn main() {\n  io.println("{} {}", 1)\n  io.println("{}", 1, 2)\n}\n')
    vetted = subprocess.run([DYN, 'vet', str(work / 'bad')], capture_output=True, text=True, timeout=60)
    assert vetted.returncode != 0, vetted
    assert 'format template has 2 {} but the call passes 1 value\n' in vetted.stderr, vetted.stderr
    assert 'format template has 1 {} but the call passes 2 values' in vetted.stderr, vetted.stderr
    built = subprocess.run([DYN, 'check', str(work / 'bad')], capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stderr
print('PASS print structs: run-time TypeInfo walk on every backend; dyn vet checks literal templates')
