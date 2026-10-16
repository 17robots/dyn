#!/usr/bin/env python3
"""Execute browser/WASI contracts without a target compiler or external linker."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
compiler = Path(os.environ.get('DYN', ROOT/'build/dyn')).resolve()
node = shutil.which('node')
if not node:
    raise SystemExit('Node is required for independent Wasm qualification')
spec = importlib.util.spec_from_file_location('wasm_runtime', ROOT/'tools/wasm-runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
with tempfile.TemporaryDirectory(prefix='dyn-independent-wasm-') as directory:
    work = Path(directory)
    # A separately emitted Basic C ABI object exercises cross-object resolution
    # without requiring Clang. wasm-browser.py also tests an actual Clang object
    # when run in the reference qualification job.
    oracle = runtime.Object()
    get, const = runtime.local, runtime.const
    oracle.function('c_pair', [runtime.I32, runtime.I32], [], [
        get(0), get(1), b'\x28\x02\x00', const(1), b'\x6a\x36\x02\x00',
        get(0), get(1), b'\x28\x02\x04', const(2), b'\x6a\x36\x02\x04'])
    oracle.function('c_single', [0x7d], [0x7d], [get(0), b'\x43\x00\x00\x80\x3f\x92'])
    oracle.write(work/'oracle.o')
    env = dict(os.environ, DYN=str(compiler), WASM_ORACLE=str(work/'oracle.o'),
               DYN_SDK=str(ROOT), DYN_LINKER='builtin', DYN_ASSEMBLY_ORACLE='0')
    if os.environ.get('DYN_TEST_INSTALLED') == '1':
        env.pop('DYN_SDK', None)
    if os.name != 'nt':
        tools = work/'tools'
        tools.mkdir()
        (tools/'node').symlink_to(node)
        env['PATH'] = str(tools)
    for name in ('wasm-browser', 'wasm-memory', 'wasi', 'wasm-semantics', 'wasm-assembly'):
        subprocess.run([sys.executable, str(ROOT/'tests'/f'{name}.py')],
                       cwd=ROOT, env=env, check=True, timeout=180)
    stack = work/'stack'
    stack.mkdir()
    (stack/'main.dyn').write_text('''marker: u32 = 1234567
pub fn value() u32 { return marker }
pub fn exhaust(n: u32) u32 {
  buffer: [65536]u8 buffer[0] = #cast(u8) n
  if n == 0 { return #cast(u32) buffer[0] }
  return exhaust(n - 1) + #cast(u32) buffer[0]
}
''')
    output = work/'stack.wasm'
    subprocess.run([str(compiler),'build',str(stack),'--target','wasm32-browser',
                    '--shared','--output',str(output)],env=env,check=True)
    subprocess.run([node,'-e','''
const assert=require('node:assert/strict');
WebAssembly.instantiate(require('node:fs').readFileSync(process.argv[1])).then(({instance:{exports:e}})=>{
  e.dyn_initialize(); assert.equal(e.exhaust(2),3);
  assert.throws(()=>e.exhaust(128),WebAssembly.RuntimeError);
  assert.equal(e.value(),1234567);
}).catch(e=>{console.error(e);process.exit(1)});
''',str(output)],env=env,check=True,timeout=30)
print('PASS independent browser/WASI execution without LLVM tools, including bounded stack frames')
