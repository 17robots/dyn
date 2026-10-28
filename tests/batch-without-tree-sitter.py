#!/usr/bin/env python3
"""The compiler does not link Tree-sitter, and batch commands never create a parser through it."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())

if not sys.platform.startswith('linux'):
    print('SKIP batch commands without Tree-sitter: needs an LD_PRELOAD host')
    sys.exit(0)
# An ASan compiler must load its runtime before any preloaded guard library.
if b'__asan_init' in Path(DYN).read_bytes():
    print('SKIP batch commands without Tree-sitter: sanitizer build cannot take LD_PRELOAD')
    sys.exit(0)

# Dynamic dependencies: no Tree-sitter library at all, editors included.
needed = subprocess.run(['readelf', '-d', DYN], capture_output=True, text=True)
if needed.returncode == 0:
    assert 'tree-sitter' not in needed.stdout, needed.stdout

GUARD = r'''
#include <stdio.h>
#include <stdlib.h>
void *ts_parser_new(void) {
  fputs("tree-sitter parser created\n", stderr);
  abort();
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-batch-tree-sitter-') as temporary:
    root = Path(temporary)
    (root/'guard.c').write_text(GUARD)
    subprocess.run([os.environ.get('CC', 'cc'), '-shared', '-fPIC', str(root/'guard.c'), '-o', str(root/'guard.so')], check=True)
    environment = dict(os.environ, LD_PRELOAD=str(root/'guard.so'))

    def project(name, files):
        directory = root/name
        for path, text in files.items():
            (directory/path).parent.mkdir(parents=True, exist_ok=True)
            (directory/path).write_text(text)
        return directory

    smoke = root/'smoke'
    shutil.copytree(ROOT/'tests/smoke', smoke)
    # Keep this formatter negative control explicit; the shared smoke source
    # may already use canonical layout.
    smoke_source = smoke/'main.dyn'
    smoke_source.write_text(smoke_source.read_text().replace('  values:', '        values:', 1))
    reflection = project('reflection', {'main.dyn': 'struct P { x: i32 }\nfn main() {\n  info := #typeof(P)\n  _ = info\n}\n'})
    gated = project('gated', {'main.dyn': '#target(kernel: darwin, arch: aarch64, abi: aapcs)\nfn f() {}\n'})
    broken = project('broken', {'main.dyn': 'fn main() {\n  x := (1 +\n}\n'})
    deep = project('deep', {'main.dyn': 'fn main(){_=' + '(' * 600 + '1' + ')' * 600 + '}\n'})
    strings = project('strings', {'main.dyn': 'fn main() {\n  _ = "//x"\n  _ = "a/*b"\n}\n'})

    def run(arguments, expected):
        result = subprocess.run([DYN, *map(str, arguments)], env=environment, capture_output=True, text=True, timeout=120)
        assert 'tree-sitter parser created' not in result.stderr, (arguments, result.stderr)
        assert result.returncode == expected, (arguments, result.returncode, result.stderr)

    for directory in (smoke, reflection, strings):
        run(['check', directory], 0)
        run(['check', '--max-work', '1000000000', directory], 0)
        run(['vet', directory], 0)
        run(['query', directory], 0)
        run(['build', directory, '--no-cache', '--quiet', '--output', root/'out'], 0)
        run(['build', directory, '--release', '--no-cache', '--quiet', '--output', root/'out'], 0)
        run(['run', directory], 0)
        run(['docs', '--json', directory], 0)
        run(['fmt', '--check', directory], 1 if directory == smoke else 0)
    run(['check', gated], 0)
    run(['build', gated, '--no-cache', '--quiet', '--output', root/'out'], 1)
    for directory in (broken, deep):
        run(['check', directory], 1)
        run(['build', directory, '--no-cache', '--quiet', '--output', root/'out'], 1)
        run(['fmt', '--check', directory], 1)
        run(['docs', directory], 1)

print('PASS batch commands without Tree-sitter: check, vet, query, build, run, docs and fmt')
