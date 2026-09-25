#!/usr/bin/env python3
"""Exercise pinned asset/UI adapters and provider alignment fixes under ASan/UBSan."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / 'build/extra-vendor-sources'
required = ['stb/stb_rect_pack.h', 'stb-build/stb_image_resize2.h',
            'microui-build/microui.h', 'microui-build/microui.c']
for name in required:
    if not (SOURCES / name).is_file():
        raise SystemExit('Missing staged provider source; run VENDOR_PACKAGES="stb microui" just vendor-libs')
env = dict(os.environ, SDL_VIDEODRIVER='dummy',
           ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',
           UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
prefix = ROOT / 'build/vendor-deps/install'
for key, suffix in [('PKG_CONFIG_PATH', 'lib/pkgconfig'), ('LD_LIBRARY_PATH', 'lib')]:
    env[key] = str(prefix / suffix) + (os.pathsep + env[key] if env.get(key) else '')
cc = shlex.split(env.get('CC', 'cc'))
flags = ['-std=c11', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
sdl = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'sdl3'], env=env, text=True))
report = {'status': 'running', 'cases': []}
output = ROOT / 'build/vendor-sanitize-results.json'
try:
    with tempfile.TemporaryDirectory(prefix='dyn-vendor-sanitize-') as directory:
        cases = [
            ('stb', [ROOT/'tests/vendor-stb-native.c', ROOT/'compiler/vendor/stb/bridge.c'],
             [SOURCES/'stb-build', SOURCES/'stb'], ['-lm']),
            ('ui', [ROOT/'tests/vendor-ui-render.c', ROOT/'compiler/vendor/microui/bridge.c',
                    SOURCES/'microui-build/microui.c', ROOT/'compiler/vendor/sdl3/microui/bridge.c'],
             [SOURCES/'microui-build'], sdl + ['-lm']),
        ]
        for name, files, includes, links in cases:
            binary = Path(directory) / name
            subprocess.run([*cc, *flags, *['-I'+str(p) for p in includes],
                            *map(str, files), *links, '-o', str(binary)],
                           env=env, check=True, timeout=120)
            subprocess.run([str(binary)], env=env, check=True, timeout=30)
            report['cases'].append(name)
    report['status'] = 'passed'
except BaseException as error:
    report.update(status='failed', error=str(error))
    raise
finally:
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2)+'\n')
print('PASS asset/UI native address, undefined-behavior and leak checks')
