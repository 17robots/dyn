#!/usr/bin/env python3
"""Qualify the shipped Tree-sitter wrapper against the native installed provider.

Requires the same C compiler, headers, library and grammar objects as build.py
host. No downloads or successful missing-provider skips. This qualifies one
provider on the executing host, not the entire vendor collection.
"""
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get('BUILD', ROOT/'build')).resolve()
DYN = Path(os.environ.get('DYN', BUILD/('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve()
CC = shlex.split(os.environ.get('CC', 'clang' if os.name == 'nt' else 'cc'))
flags = shlex.split(os.environ.get('CPPFLAGS', ''))
env = dict(os.environ)
version = None
pkg_config = shutil.which('pkg-config')
if pkg_config:
    query = subprocess.run([pkg_config, '--cflags', '--libs', 'tree-sitter'], capture_output=True, text=True)
    if query.returncode == 0:
        flags += shlex.split(query.stdout)
        version = subprocess.check_output([pkg_config, '--modversion', 'tree-sitter'], text=True).strip()
# Use the compiler's own library search when pkg-config is unavailable (notably
# CLANG64). Homebrew's explicit -L in CPPFLAGS is honored without calling brew.
name = 'libtree-sitter.dll.a' if os.name == 'nt' else 'libtree-sitter.dylib' if platform.system() == 'Darwin' else 'libtree-sitter.so'
query = subprocess.run([*CC, '-print-file-name=' + name], capture_output=True, text=True, check=True)
library = Path(query.stdout.strip())
if library.is_file():
    flags += ['-L' + str(library.resolve().parent)]
directories = []
for index, flag in enumerate(flags):
    if flag == '-L' and index + 1 < len(flags):
        directories.append(flags[index + 1])
    elif flag.startswith('-L') and len(flag) > 2:
        directories.append(flag[2:])
for key in ('DYN_LIBRARY_PATH', 'PATH' if os.name == 'nt' else 'DYLD_LIBRARY_PATH' if platform.system() == 'Darwin' else 'LD_LIBRARY_PATH'):
    paths = [str(Path(path).resolve().parent/'bin') for path in directories] if key == 'PATH' else directories
    env[key] = os.pathsep.join([*paths, *([env[key]] if env.get(key) else [])])
objects = [BUILD/'tree-sitter-dyn-parser.o', BUILD/'tree-sitter-dyn-scanner.o']
for path in [DYN, *objects]:
    if not path.is_file():
        raise RuntimeError('Missing required native compiler artifact: ' + str(path))
LAYOUTS = {'Point': ('TSPoint', ['row', 'column']),
           'Edit': ('TSInputEdit', ['start_byte', 'old_end_byte', 'new_end_byte', 'start_point', 'old_end_point', 'new_end_point']),
           'Node': ('TSNode', ['context', 'id', 'tree'])}
C = '''#include <tree_sitter/api.h>
#include <stddef.h>
#include <stdio.h>
extern const TSLanguage *tree_sitter_dyn(void);
int main(void) {
 printf("abi %u\\n", ts_language_abi_version(tree_sitter_dyn()));
 printf("minimum %u\\n", TREE_SITTER_MIN_COMPATIBLE_LANGUAGE_VERSION);
 printf("maximum %u\\n", TREE_SITTER_LANGUAGE_VERSION);
'''
for dyn, (native, fields) in LAYOUTS.items():
    C += f'printf("{dyn}.size %zu\\n", sizeof({native}));\n'
    C += f'printf("{dyn}.align %zu\\n", _Alignof({native}));\n'
    for field in fields:
        C += f'printf("{dyn}.{field} %zu\\n", offsetof({native}, {field}));\n'
C += '}\n'
SOURCE = r'''use "vendor/tree_sitter" ts
use "std/bytes"
use "std/io"
extern fn grammar "tree_sitter_dyn"() ts.Language
fn require(ok: bool) { if !ok { #panic("Tree-sitter provider contract") } }
fn main() {
LAYOUT
  // Repetition exercises ordinary create/copy/free and failed-parse cleanup.
  for iteration in 0..32 {
    _ = iteration
    parser := ts.parser_create_owned()
    require(parser != nil)
    require(!ts.parser_language(parser, nil))
    require(ts.parser_language(parser, grammar()))
    parsed := ts.parse(parser, nil, "fn main() {}")
    require(parsed.ok)
    node := ts.root(parsed.tree)
    require(ts.node_valid(node) && !ts.node_has_error(node))
    require(ts.node_start(node) == 0 && ts.node_end(node) == 12)
    require(ts.child_count(node) == 1)
    kind := ts.node_type(node, 64)
    require(kind.ok && bytes.equal(kind.value, "source_file"))
    copy := ts.tree_copy_owned(parsed.tree)
    require(copy != nil)
    ts.tree_destroy_owned(parsed.tree)
    // The copied tree remains live after the original is destroyed.
    require(ts.node_end(ts.root(copy)) == 12)
    edit := ts.Edit{ start_byte: 11, old_end_byte: 11, new_end_byte: 12,
      start_point: ts.Point{ column: 11 }, old_end_point: ts.Point{ column: 11 }, new_end_point: ts.Point{ column: 12 } }
    require(ts.tree_edit(copy, &edit))
    reparsed := ts.parse(parser, copy, "fn main() { }")
    require(reparsed.ok && ts.node_end(ts.root(reparsed.tree)) == 13)
    ts.tree_destroy_owned(copy)
    ts.tree_destroy_owned(reparsed.tree)
    broken := ts.parse(parser, nil, "fn main( {")
    require(broken.ok && ts.node_has_error(ts.root(broken.tree)))
    ts.tree_destroy_owned(broken.tree)
    ts.parser_destroy_owned(parser)
  }
  ts.tree_destroy_owned(nil)
  ts.parser_destroy_owned(nil)
  require(!ts.parse(nil, nil, "").ok)
  _ = io.println(io.stdout(), "tree-sitter provider ok")
}
'''
report = {'provider': 'tree-sitter', 'pkg_config_version': version,
          'host': platform.system(), 'machine': platform.machine(), 'modes': [], 'status': 'running'}
(BUILD/'vendor-provider-host.json').write_text(json.dumps(report, indent=2)+'\n')
with tempfile.TemporaryDirectory(prefix='dyn-tree-sitter-provider-') as temporary:
    work = Path(temporary)
    (work/'oracle.c').write_text(C)
    oracle = work/('oracle.exe' if os.name == 'nt' else 'oracle')
    subprocess.run([*CC, '-std=c11', str(work/'oracle.c'), *map(str, objects),
                    *flags, '-ltree-sitter', '-o', str(oracle)], env=env, check=True, timeout=60)
    output = subprocess.check_output([str(oracle)], env=env, text=True, timeout=10)
    values = {key: int(value) for key, value in (line.split() for line in output.splitlines())}
    assert values['minimum'] <= values['abi'] <= values['maximum'], values
    report['native_oracle'] = values
    assertions = []
    for dyn, (_, fields) in LAYOUTS.items():
        assertions += [f'  require(#sizeof(ts.{dyn}) == {values[dyn+".size"]})',
                       f'  require(#alignof(ts.{dyn}) == {values[dyn+".align"]})',
                       f'  layout_{dyn} := ts.{dyn}{{}}']
        for field in fields:
            assertions.append(f'  require(#cast(usize) &layout_{dyn}.{field} - #cast(usize) &layout_{dyn} == {values[dyn+"."+field]})')
    (work/'main.dyn').write_text(SOURCE.replace('LAYOUT', '\n'.join(assertions)))
    for release in (False, True):
        binary = work/('probe.exe' if os.name == 'nt' else 'probe')
        subprocess.run([str(DYN), 'build', str(work), '--quiet', '--no-cache', '--output', str(binary),
                        *[item for path in objects for item in ('--link', str(path))],
                        *(['--release'] if release else [])], env=env, check=True, timeout=90)
        result = subprocess.run([str(binary)], env=env, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0 and result.stdout == 'tree-sitter provider ok\n', (result.returncode, result.stdout, result.stderr)
        report['modes'].append('release' if release else 'debug')
report['status'] = 'passed'
(BUILD/'vendor-provider-host.json').write_text(json.dumps(report, indent=2)+'\n')
print('PASS native Tree-sitter ABI, layout, parse/edit/copy/destruction: debug/release')
