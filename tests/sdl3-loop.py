#!/usr/bin/env python3
"""Run the actual interactive example against SDL lifecycle contract doubles."""
import os, pathlib, subprocess, tempfile
root = pathlib.Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='dyn-sdl-loop-') as directory:
    work = pathlib.Path(directory)
    mock = work / 'sdl.so'
    subprocess.run(['cc', '-shared', '-fPIC', str(root/'tests/sdl3-loop/mock.c'), '-o', str(mock)], check=True)
    for project in ('stuff-sdl', 'sdl3-gpu-example', 'sdl3-example', 'window'):
      for mode in ([], ['--release']):
        binary = work/'example'
        subprocess.run([os.environ.get('DYN', str(root/'build/dyn')), 'build', str(root/'projects'/project), '--no-cache', '--output', str(binary), *mode], check=True)
        for minimized in ('', '1'):
            env = dict(os.environ, LD_PRELOAD=str(mock), DYN_TEST_MINIMIZED=minimized)
            if project in ('sdl3-example', 'window'): env['DYN_TEST_RENDERER'] = '1'
            result = subprocess.run([str(binary)], env=env, capture_output=True, text=True, timeout=5)
            assert result.returncode == 0, result.stdout + result.stderr
            assert 'PASS three frames then quit' in result.stdout, result.stdout
print('PASS SDL GPU example lifecycle, debug/release')
