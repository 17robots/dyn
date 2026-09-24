#!/usr/bin/env python3
"""Cache reuse preserves runtime results through implementation and ABI edits."""
import os
from pathlib import Path
import subprocess
import tempfile

DYN = str(Path(os.environ.get('DYN', 'build/dyn')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-cache-edits-') as directory:
    root = Path(directory)/'app'; root.mkdir()
    for name in ('library', 'other'): (root/name).mkdir()
    (root/'main.dyn').write_text('use "./library" lib\nuse "./other" other\nfn main() { _ = #syscall(60, lib.answer() + other.zero()) }\n')
    library = root/'library/module.dyn'
    (root/'other/module.dyn').write_text('pub fn zero() i32 { return 0 }\n')
    template = 'fn hidden() i32 { return VALUE }\npub fn answer() i32 { return hidden() }\n'
    output = Path(directory)/'program'
    environment = dict(os.environ, DYN_CACHE_DIR=str(Path(directory)/'cache'))
    for mode in ([], ['--release']):
        for step, value in enumerate((41, 41, 42, 43)):
            text = template.replace('VALUE', str(value))
            if step == 3: text += 'pub struct Added { value: i32 }\n'
            library.write_text(text)
            built = subprocess.run([DYN, 'build', str(root), '--quiet', '--verbose', '--jobs', '2', '--output', str(output), *mode],
                                   env=environment, capture_output=True, text=True, check=True)
            assert subprocess.run([str(output)]).returncode == value, (mode, step, built.stderr)
            if step == 2:
                assert built.stderr.count('cached module ') == 2, built.stderr
            if step == 3:
                assert built.stderr.count('cached module ') == 1, built.stderr
                assert str(root/'other/module.dyn') in built.stderr, built.stderr
print('PASS incremental unchanged/private/public edits: runtime results and module reuse, debug/release')

with tempfile.TemporaryDirectory(prefix='dyn-transitive-cache-') as directory:
    root = Path(directory)/'app'; root.mkdir()
    for name in ('base', 'wrapper', 'unrelated'): (root/name).mkdir()
    (root/'main.dyn').write_text('use "./wrapper" w\nuse "./unrelated" u\nfn main() { _ = #syscall(60, w.answer() + u.zero()) }\n')
    (root/'wrapper/module.dyn').write_text('use "../base" b\npub fn answer() i32 { return b.value }\n')
    (root/'unrelated/module.dyn').write_text('pub fn zero() i32 { return 0 }\n')
    base = root/'base/module.dyn'
    output = Path(directory)/'program'
    for mode in ([], ['--release']):
        environment = dict(os.environ, DYN_CACHE_DIR=str(Path(directory)/('release' if mode else 'debug')))
        for value in (41, 42):
            base.write_text(f'pub const value: i32 = {value}\n')
            run = subprocess.run([DYN, 'build', str(root), '--quiet', '--verbose', '--jobs', '2', '--output', str(output), *mode],
                                 env=environment, capture_output=True, text=True, check=True)
            assert subprocess.run([str(output)]).returncode == value, run.stderr
            if value == 42:
                assert run.stderr.count('cached module ') == 1, run.stderr
                assert 'cached module '+str(root/'unrelated/module.dyn') in run.stderr, run.stderr
print('PASS transitive public-constant invalidation and unrelated module reuse')

with tempfile.TemporaryDirectory(prefix='dyn-reflection-cache-') as directory:
    root = Path(directory)/'app'; root.mkdir(); (root/'lib').mkdir()
    (root/'main.dyn').write_text('use "./lib" lib\nfn main() { _ = #syscall(60, lib.answer()) }\n')
    library = root/'lib/module.dyn'; output = Path(directory)/'program'
    for mode in ([], ['--release']):
        env = dict(os.environ, DYN_CACHE_DIR=str(Path(directory)/('release' if mode else 'debug')))
        for step in range(4):
            reflected = '_ = #typeof(i32) ' if step in (1, 2) else ''
            library.write_text(f'pub fn answer() i32 {{ {reflected}return {40+step} }}\n')
            run = subprocess.run([DYN,'build',str(root),'--quiet','--verbose','--output',str(output),*mode],
                                 env=env,capture_output=True,text=True,check=True)
            assert subprocess.run([str(output)]).returncode == 40+step, run.stderr
            if step in (1, 2): assert 'cached module ' not in run.stderr, (mode,step,run.stderr)
            # Removing reflection can reuse the previously built non-reflection root.
            if step == 3: assert run.stderr.count('cached module ') == 1, (mode,step,run.stderr)
print('PASS reflection mode changes and implementation edits use correct module objects')
