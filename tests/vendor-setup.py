#!/usr/bin/env python3
"""Installed raw SDK tools, quoted activation paths, and the shipped Lua lesson."""
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
env = dict(os.environ)
with tempfile.TemporaryDirectory(prefix='dyn-vendor-setup-') as directory:
    work = Path(directory)
    stage = work / 'stage'
    subprocess.run(['just', '--justfile', str(ROOT / 'compiler/justfile'), 'install'],
                   env=dict(env, DESTDIR=str(stage), PREFIX='/sdk with space'), stdout=subprocess.DEVNULL, check=True, timeout=180)
    sdk = stage / 'sdk with space'
    command = [str(sdk / 'bin/dyn-bind-vendors')]
    listed = subprocess.run([*command, '--list'], env=env, text=True, capture_output=True, check=True, timeout=30)
    assert 'lua\tvendor/lua/raw' in listed.stdout
    overlay = work / "overlay's $literal path"
    (overlay/'std/mem').mkdir(parents=True)
    (overlay/'std/mem/stale.dyn').write_text('invalid obsolete std adapter')
    built = subprocess.run([*command, 'lua', '--prefix', str(ROOT / 'build/vendor-deps/install'),
                            '--sources', str(ROOT / 'build/extra-vendor-sources'), '--output', str(overlay)],
                           env=env, text=True, capture_output=True, timeout=180)
    assert built.returncode == 0, built.stdout + built.stderr
    assert not (overlay/'std/mem/stale.dyn').exists()
    parent = dict(env, DYN_LIBRARY_PATH='/existing/dyn', LD_LIBRARY_PATH='/existing/native')
    script = '. "$1"; exec "$2" -c \'import json,os; print(json.dumps(dict(os.environ)))\''
    active = subprocess.run(['sh', '-c', script, 'activate', str(overlay / 'env.sh'), sys.executable],
                            env=parent, text=True, capture_output=True, check=True, timeout=30)
    active_env = json.loads(active.stdout)
    assert active_env['DYN_SDK'] == str(overlay)
    assert active_env['DYN_LIBRARY_PATH'].endswith(':/existing/dyn')
    assert active_env['LD_LIBRARY_PATH'].endswith(':/existing/native')
    for mode in ([], ['--release']):
        binary = work / 'example'
        subprocess.run([active_env['DYN'], 'build', str(overlay / 'examples/lua'), '--quiet',
                        '--no-cache', '--output', str(binary), *mode], env=active_env, check=True, timeout=120)
        result = subprocess.run([str(binary)], env=active_env, text=True, capture_output=True, check=True, timeout=30)
        assert result.stdout.strip() == 'retained result', result.stdout
    subprocess.run([sys.executable, str(ROOT/'tests/wasm-browser.py')],
                   env=dict(active_env, DYN=str(sdk/'bin/dyn')), check=True, timeout=120)
    for name in ('wasm-memory.py', 'wasi.py'):
        subprocess.run([sys.executable, str(ROOT/'tests'/name)],
                       env=dict(active_env, DYN=str(sdk/'bin/dyn')), check=True, timeout=120)
    browser = work/'browser assets'
    browser.mkdir()
    cached = ROOT/'build/browser-ffmpeg/core.tgz'
    if cached.is_file(): shutil.copy2(cached, browser/'core.tgz')
    subprocess.run([str(sdk/'bin/dyn-browser-ffmpeg'), '--output', str(browser)],
                   env=env, check=True, timeout=180)
    assert (browser/'worker.js').read_bytes() == (sdk/'share/dyn/vendor/ffmpeg/browser/worker.js').read_bytes()
    assert (browser/'ffmpeg-core.wasm').stat().st_size > 1000000
    coverage = json.loads((overlay / 'vendor/lua/raw/coverage.json').read_text())
    assert 'lua_pop' in coverage['macro_helpers']
    assert 'lua_pop' not in coverage['untranslated_function_macros']
print('PASS installed SDK helpers, activation quoting/path preservation, and native lifetime example')
