#!/usr/bin/env python3
"""&T{...} points at the literal's own writable storage on every backend;
returning it, &f(), and storing a local's address through a parameter or into
a global are errors."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"

struct P { x: i64, y: i64 }

fn bump(p: *P) i64 {
  p.x += 1
  return p.x + p.y
}

fn keep(a: *P, b: *P) i64 {
  a.x = 100
  return b.x
}

fn main() {
  io.println("{}", bump(&P{ x: 1, y: 2 }))
  p := &P{ x: 5, y: 6 }
  p.y = 7
  io.println("{} {}", p.x, p.y)
  io.println("{}", keep(&P{ x: 1, y: 1 }, &P{ x: 1, y: 1 }))
  total: i64 = 0
  for i in 0..3 {
    q := &P{ x: #cast(i64, i), y: 0 }
    q.y = q.x * 10
    total += q.y
  }
  io.println("{}", total)
}
'''
EXPECTED = '4\n5 7\n1\n30\n'
WASI = r'''
const {WASI}=require('node:wasi'),fs=require('fs');
(async()=>{const wasi=new WASI({version:'preview1',args:['test'],returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});
'''
ERRORS = (
    ('fn make() *P {\n  return &P{ x: 1, y: 2 }\n}\n', 'returned value borrows function-local storage'),
    ('fn make() P {\n  return P{ x: 1, y: 2 }\n}\n\nfn use_it() i64 {\n  p := &make()\n  return p.x\n}\n',
     'a call result has no storage to point at'),
    ('struct H { p: *P }\n\nfn fill(h: *H) {\n  local := P{ x: 1, y: 2 }\n  h.p = &local\n}\n',
     'stores the address of function-local storage where it outlives the function'),
    ('struct H { p: *P }\n\nfn fill(h: *H) {\n  h.p = &P{ x: 1, y: 2 }\n}\n',
     'stores the address of function-local storage where it outlives the function'),
)
with tempfile.TemporaryDirectory(prefix='dyn-address-literal-') as temporary:
    work = Path(temporary)
    project = work / 'ok'
    project.mkdir()
    (project / 'main.dyn').write_text(SOURCE)
    for name, flags, env, emulator in (
            ('debug', ['--debug'], {}, []), ('release', ['--release'], {}, []),
            ('o3', ['--release', '--opt-level', '3'], {}, []),
            ('tree', ['--release'], {'DYN_NO_SSA': '1'}, []), ('tree-debug', ['--debug'], {'DYN_NO_SSA': '1'}, []),
            ('arm', ['--target', 'aarch64-linux', '--release'], {}, ['qemu-aarch64']),
            ('riscv', ['--target', 'riscv64-linux', '--release'], {}, ['qemu-riscv64']),
            ('wasi.wasm', ['--target', 'wasm32-wasi'], {}, ['node', '--no-warnings', '-e', WASI]),
            ('wasi-release.wasm', ['--target', 'wasm32-wasi', '--release'], {}, ['node', '--no-warnings', '-e', WASI])):
        program = work / name
        built = subprocess.run([DYN, 'build', str(project), *flags, '--no-cache', '--quiet', '--output', str(program)],
                               capture_output=True, text=True, timeout=180, env={**os.environ, **env})
        assert built.returncode == 0, (name, built.stderr)
        if emulator and not shutil.which(emulator[0]):
            continue
        result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0 and result.stdout == EXPECTED, (name, result)
    for index, (body, message) in enumerate(ERRORS):
        bad = work / f'bad{index}'
        bad.mkdir()
        (bad / 'main.dyn').write_text('struct P { x: i64, y: i64 }\n\n' + body + '\nfn main() {\n}\n')
        checked = subprocess.run([DYN, 'check', str(bad)], capture_output=True, text=True, timeout=60)
        assert checked.returncode != 0 and message in checked.stderr, (body, checked.stderr)
print('PASS address of a literal: &T{...} on every backend; returns, &f() and stores through parameters rejected')
