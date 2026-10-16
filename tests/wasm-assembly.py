#!/usr/bin/env python3
"""Emit Wasm assembly tool-free, then independently assemble/link/execute it.

The optional oracle phase uses Clang solely to consume the emitted text.
Set DYN_ASSEMBLY_ORACLE=0 for environments without reference tools.
"""
import ast
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build' / ('dyn.exe' if os.name == 'nt' else 'dyn'))).resolve()


def run(command, **kwargs):
    p = subprocess.run(list(map(str, command)), text=True, capture_output=True, timeout=90, **kwargs)
    assert p.returncode == 0, (command, p.returncode, p.stdout, p.stderr)
    return p


# Share behavior assertions with the object backend suite; roundtripping must
# preserve observable arithmetic, aliasing, indirect calls, and checked cleanup.
constants = {}
for node in ast.parse((ROOT / 'tests/wasm-semantics.py').read_text()).body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        if node.targets[0].id in ('SOURCE', 'JS'):
            constants[node.targets[0].id] = ast.literal_eval(node.value)
with tempfile.TemporaryDirectory(prefix='dyn-wasm-assembly-') as temporary:
    root = Path(temporary)
    project = root / 'project'; project.mkdir()
    (project / 'main.dyn').write_text(constants['SOURCE'] + '''
pub fn constant_bits() f64 { value: u64 = 0x7ff8000000000042 return #bitcast(f64) value }
pub fn text() []const u8 { return "assembly data" }
''')
    empty = root / 'empty'; empty.mkdir()
    environment = dict(os.environ, DYN_SDK=str(ROOT), DYN_LINKER='builtin')
    # Windows needs PATH to locate the host compiler's MinGW runtime DLLs,
    # just as in wasm-independent.py. Unix can isolate target tools entirely.
    if os.name != 'nt':
        environment['PATH'] = str(empty)
    if os.environ.get('DYN_TEST_INSTALLED') == '1':
        environment.pop('DYN_SDK', None)
    oracle = os.environ.get('DYN_ASSEMBLY_ORACLE', '1') != '0'
    if oracle:
        cc = shlex.split(os.environ.get('CC', 'cc'))
        clang = shlex.split(os.environ.get('CLANG', 'clang'))
        node = shutil.which('node')
        assert node, 'Node required for assembly execution oracle'
        harness = root / 'link.c'
        harness.write_text('#include "link_wasm.h"\nint main(int n,char **v) {'
                           'const char *allowed[]={"note"};'
                           'return dyn_link_wasm_objects((const char *const *)v+2,n-2,v[1],allowed,1,0,0,0);}\n')
        linker = root / ('link.exe' if os.name == 'nt' else 'link')
        run([*cc, '-std=c11', '-I', ROOT / 'src', harness, ROOT / 'src/link_wasm.c', '-o', linker])
        runtime = root / 'dynrt_wasm.o'
        run([sys.executable, ROOT / 'tools/wasm-runtime.py', '--output', runtime])
    for mode in ('debug', 'release'):
        output = root / ('module-' + mode + '.wasm')
        run([DYN, 'build', project, '--target', 'wasm32-browser', '--shared', '--backend', 'native',
             '--' + mode, '--emit-asm', '--output', output], env=environment)
        assembly = Path(str(output) + '.s')
        assert assembly.exists(), list(root.iterdir())
        text = assembly.read_text()
        for required in ('.functype', 'call_indirect', '.export_name', '__stack_pointer', 'end_function'):
            assert required in text, required
        if oracle:
            obj = root / ('roundtrip-' + mode + '.o')
            rebuilt = root / ('roundtrip-' + mode + '.wasm')
            # Clang 19 does not enable Wasm bulk memory by default.
            run([*clang, '--target=wasm32', '-mbulk-memory', '-c', assembly, '-o', obj])
            run([linker, rebuilt, obj, runtime])
            run([node, '-e', constants['JS'], rebuilt])
    print('PASS Wasm stack assembly emitted' + (' with empty PATH' if os.name != 'nt' else '') + ('; independently assembled and executed debug/release' if oracle else ''))
