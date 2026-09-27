#!/usr/bin/env python3
"""Large value copies stay bounded and retain independent value semantics."""
import os
import re
from pathlib import Path
import subprocess
import tempfile

DYN = str(Path(os.environ.get('DYN', './build/dyn')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-aggregate-copy-') as directory:
    root = Path(directory)
    (root / 'main.dyn').write_text('''
struct Large { bytes: [32768]u8, marker: i64 }
struct App { config: Large }
fn reset(target: *Large) { target.* = Large{marker: target.marker + 1} }
fn main() {
    parsed := Large{}
    parsed.bytes[32767] = 93
    parsed.marker = 47
    copied := parsed
    app := App{}
    app.config = parsed
    app.config = app.config
    bytes := copied.bytes
    other: [32768]u8 = []
    other = bytes
    bytes[32767] = 5
    parsed.bytes[32767] = 11
    parsed.marker = 12
    if copied.bytes[32767] != 93 || app.config.bytes[32767] != 93 || app.config.marker != 47 || other[32767] != 93 {
        #panic("aggregate copy did not preserve values")
    }
    reset(&app.config)
    if app.config.bytes[32767] != 0 || app.config.marker != 48 { #panic("aliased aggregate initializer") }
}
''')
    output = root / 'program'
    emitted = subprocess.run([DYN, 'build', str(root), '--emit-ir', '--no-link',
                              '--output', str(output)], capture_output=True, text=True, timeout=30)
    assert emitted.returncode == 0, emitted.stderr
    ir = output.with_suffix('.ll').read_text()
    assert 'llvm.memmove' in ir, 'aggregate copies still materialize whole SSA values'
    reset_ir = re.search(r'define [^\n]*@reset\(.*?\n}', ir, re.S)
    assert reset_ir, 'missing reset function in emitted IR'
    assert 'insertvalue' not in reset_ir[0], 'aggregate assignment still expands a literal as an SSA value'
    for mode in ([], ['--release']):
        built = subprocess.run([DYN, 'build', str(root), '--no-cache', '--jobs', '1',
                                '--output', str(output), *mode], capture_output=True, text=True, timeout=30)
        assert built.returncode == 0, built.stderr
        subprocess.run([str(output)], check=True, timeout=5)
print('PASS bounded aggregate copies, independent values, field assignment, self-assignment (debug/release)')
