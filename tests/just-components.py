#!/usr/bin/env python3
"""Exercise independent component checkouts without the root dispatcher or fixtures."""
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT/'build/just-components.log'
env = dict(os.environ)
# An inherited workspace compiler/SDK must not mask standalone path mistakes.
for name in ('DYN', 'DYN_SDK', 'BUILD', 'WORKSPACE', 'COMPILER_DIR', 'TS_DIR', 'PROJECTS_DIR', 'PREFIX', 'DESTDIR'):
    env.pop(name, None)
ignore = shutil.ignore_patterns('.jj', '.git', 'build', 'target', 'node_modules', '__pycache__', '*.o', '*.so', '*.wasm', '*.pyc')
with tempfile.TemporaryDirectory(prefix='dyn-components-') as directory, LOG.open('w') as log:
    work = Path(directory)
    compiler = work/'compiler checkout'
    grammar = work/'grammar-checkout'
    projects = work/'projects-checkout'
    for source, destination in [('compiler', compiler), ('tree-sitter-dyn', grammar), ('projects', projects)]:
        shutil.copytree(ROOT/source, destination, ignore=ignore)
    assert not (work/'justfile').exists()
    def run(component, *recipes, **overrides):
        subprocess.run(["just", "--justfile", str(component/"justfile"), *recipes], cwd=work, env=dict(env, **{k: str(v) for k,v in overrides.items()}), stdout=log, stderr=subprocess.STDOUT, check=True, timeout=240)
    run(grammar, 'package')
    grammar_unpacked = work/'grammar unpacked'
    grammar_unpacked.mkdir()
    with tarfile.open(grammar/'build/dist/dyn-grammar-candidate.tar.gz') as archive:
        archive.extractall(grammar_unpacked, filter='data')
    # justfile/tools must be present in actual artifact, not just checkout.
    run(grammar_unpacked, 'release')
    run(compiler, 'release', 'smoke', TS_DIR=grammar_unpacked)
    # Incremental builds must retain outputs, notice included source changes,
    # invalidate on command changes, and propagate compiler failures.
    binary = compiler/'build/dyn-release'
    unchanged = binary.stat().st_mtime_ns
    run(compiler, 'artifact', 'dyn-release', TS_DIR=grammar_unpacked)
    assert binary.stat().st_mtime_ns == unchanged, 'unchanged compiler rebuilt'
    source = compiler/'src/target.c'
    source.write_text(source.read_text() + '\n// incremental rebuild probe\n')
    run(compiler, 'artifact', 'dyn-release', TS_DIR=grammar_unpacked)
    assert binary.stat().st_mtime_ns != unchanged, 'unity include change was missed'
    obj = compiler/'build/tree-sitter-dyn-parser.o'
    unchanged = obj.stat().st_mtime_ns
    run(compiler, 'artifact', 'tree-sitter-dyn-parser.o', TS_DIR=grammar_unpacked, CC='cc -DDYN_BUILD_PROBE=1')
    assert obj.stat().st_mtime_ns != unchanged, 'compiler command change was missed'
    failed = subprocess.run(['just', '--justfile', str(compiler/'justfile'), 'artifact', 'tree-sitter-dyn-parser.o'],
                            env=dict(env, TS_DIR=str(grammar_unpacked), CC='false'), stdout=log, stderr=subprocess.STDOUT)
    assert failed.returncode != 0, 'compiler failure was hidden'
    run(compiler, 'package', TS_DIR=grammar_unpacked)
    sdk_unpacked = work/'sdk unpacked'
    sdk_unpacked.mkdir()
    with tarfile.open(compiler/('build/dist/dyn-'+os.environ.get('DYN_VERSION','0.1.0-dev')+'-linux-x86_64.tar.gz')) as archive:
        archive.extractall(sdk_unpacked, filter='data')
    dyn = sdk_unpacked/'dyn-sdk/bin/dyn'
    run(projects, 'test', DYN=dyn)
    run(projects, 'package')
    projects_unpacked = work/'projects-unpacked'
    projects_unpacked.mkdir()
    with tarfile.open(projects/'build/dist/dyn-projects-candidate.tar.gz') as archive:
        archive.extractall(projects_unpacked, filter='data')
    run(projects_unpacked, 'run', PROJECT='memory-tour', DYN=dyn)
    # Component clean must not remove a sibling's sentinel or source file.
    sentinel = work/'keep.txt'
    sentinel.write_text('keep')
    for component in (compiler, grammar_unpacked, projects_unpacked):
        unsafe = subprocess.run(['just', '--justfile', str(component/'justfile'), 'clean'], env=dict(env, BUILD=str(component)), stdout=log, stderr=subprocess.STDOUT)
        assert unsafe.returncode != 0 and (component/'justfile').exists(), 'unsafe clean accepted'
        run(component, 'clean')
        assert (component/'justfile').exists() and sentinel.read_text() == 'keep'
print(f'PASS isolated compiler, grammar and projects releases; log: {LOG}')
