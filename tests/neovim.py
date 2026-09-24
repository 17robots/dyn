#!/usr/bin/env python3
"""Run real Neovim completion and edit/highlight regressions with bounded lifetimes."""
import os
from pathlib import Path
import shutil
import shlex
import tempfile
import subprocess
ROOT = Path(__file__).resolve().parents[1]
if not shutil.which('nvim'):
    if os.environ.get('DYN_REQUIRE_ALL') == '1': raise SystemExit('Neovim 0.11+ required')
    print('SKIP Neovim: nvim unavailable')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-nvim-parser-') as directory:
    parser = Path(directory)/'dyn.so'
    subprocess.run([*shlex.split(os.environ.get('CC','cc')), '-shared', '-fPIC',
                    '-I'+str(ROOT/'tree-sitter-dyn/src'),
                    str(ROOT/'tree-sitter-dyn/src/parser.c'), str(ROOT/'tree-sitter-dyn/src/scanner.c'),
                    '-o', str(parser)], check=True)
    env = dict(os.environ, DYN_NVIM_PARSER=str(parser))
    for script in ('nvim-completion.lua', 'nvim-edits.lua'):
        subprocess.run(['nvim', '--clean', '--headless', '-c', 'luafile tests/'+script], cwd=ROOT, env=env, check=True, timeout=40)
