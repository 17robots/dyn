#!/usr/bin/env python3
"""Install compiler artifacts and SDK sources, or clean the selected build directory."""
import os
from pathlib import Path
import shutil
import sys

COMPILER = Path(__file__).resolve().parents[1]
WORKSPACE = Path(os.environ.get('WORKSPACE', COMPILER.parent)).resolve()
BUILD = Path(os.environ.get('BUILD', COMPILER/'build')).resolve()
if sys.argv[1:] == ['--clean']:
    if BUILD in (Path('/'), COMPILER, WORKSPACE) or COMPILER.is_relative_to(BUILD):
        sys.exit('Refusing unsafe BUILD for clean')
    if BUILD.exists():
        shutil.rmtree(BUILD)
else:
    prefix = Path(os.environ.get('DESTDIR', '') + os.environ.get('PREFIX', '/usr/local'))
    for relative in ('bin', 'lib/dyn', 'share/dyn'):
        (prefix/relative).mkdir(parents=True, exist_ok=True)
    programs = {'dyn': BUILD/'dyn-release', 'dyn-query': COMPILER/'tools/dyn-query.py',
                'dyn-sandbox': COMPILER/'tools/dyn-sandbox.py', 'dyn-browser-ffmpeg': COMPILER/'tools/setup-browser-ffmpeg.py',
                'dyn-bind': COMPILER/'tools/dyn-bind.py', 'dyn-build-vendors': COMPILER/'tools/build-vendors.py',
                'dyn-bind-vendors': COMPILER/'tools/bind-vendors.py', 'dyn-raw-bind': COMPILER/'tools/vendor-bindings.py'}
    for name, source in programs.items():
        destination = prefix/'bin'/name
        shutil.copyfile(source, destination)
        destination.chmod(0o755)
    # Use the build manifest's runtime list rather than a glob that could package stale objects.
    from build import ALL
    for name in ALL:
        if name.startswith('dynrt_'):
            destination = prefix/'lib/dyn'/name
            shutil.copyfile(BUILD/name, destination)
            destination.chmod(0o644)
    shutil.copy2(COMPILER/'LICENSE', prefix/'share/dyn/LICENSE')
    shutil.copy2(COMPILER/'THIRD_PARTY_NOTICES.md', prefix/'share/dyn/THIRD_PARTY_NOTICES.md')
    shutil.copytree(COMPILER/'std', prefix/'share/dyn', dirs_exist_ok=True)
    shutil.copytree(COMPILER/'vendor', prefix/'share/dyn/vendor', dirs_exist_ok=True)
