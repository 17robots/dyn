#!/usr/bin/env python3
"""Run optional native bindings against real providers, offline, debug and release.

--require-all turns missing dependencies into failures. Local builds under
build/vendor-deps/install are discovered without installing system packages.
"""
import argparse
import http.server
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess
import tempfile
import threading
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--require-all', action='store_true', default=os.environ.get('DYN_REQUIRE_ALL') == '1')
options = parser.parse_args()
env = dict(os.environ)
local = ROOT/'build/vendor-deps/install'
for key, suffix in [('PKG_CONFIG_PATH', 'lib/pkgconfig'), ('DYN_LIBRARY_PATH', 'lib'), ('LD_LIBRARY_PATH', 'lib')]:
    env[key] = str(local/suffix) + (os.pathsep + env[key] if env.get(key) else '')
dyn = str(Path(env.get('DYN', ROOT/'build/dyn')).resolve())
results = []

def available(packages):
    return subprocess.run(['pkg-config', '--exists', *packages], env=env).returncode == 0

def run(command, **kwargs):
    return subprocess.run(command, cwd=ROOT, env=kwargs.pop('env', env), check=True, timeout=60, **kwargs)

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'vendor transfer\n'
        self.send_response(404 if self.path == '/missing' else 200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass

with tempfile.TemporaryDirectory(prefix='dyn-vendors-') as directory:
    work = Path(directory)
    def png_chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind+data))
    image = work/'pixel.png'
    image.write_bytes(b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)) + png_chunk(b'IDAT', zlib.compress(b'\0\xff\0\0\xff')) + png_chunk(b'IEND', b''))
    archive = work/'sample.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as writer:
        writer.writestr('hello.txt', 'archive payload\n')
    invalid = work/'invalid.zip'
    invalid.write_bytes(b'not an archive')
    fonts = [Path(env['DYN_TEST_FONT'])] if env.get('DYN_TEST_FONT') else list(Path('/usr/share/fonts').rglob('DejaVuSans.ttf'))
    font = str(fonts[0]) if fonts else None
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/'
    # Avoid host proxy configuration for local deterministic transfers.
    env['NO_PROXY'] = env['no_proxy'] = '127.0.0.1'
    cases = [
        ('tree-sitter-example', ['tree-sitter', 'tree-sitter-c'], [], 'incrementally reparsed'),
        ('regex-example', ['libpcre2-8'], [], 'captured ada'),
        ('lua-example', ['lua5.4'], [], 'balanced stack'),
        ('archive-example', ['libarchive'], [str(archive)], 'hello.txt\narchive payload'),
        ('curl-example', ['libcurl'], [url], 'HTTP 200\nvendor transfer'),
        ('sdl3-image-example', ['sdl3', 'sdl3-image'], [str(image)], 'decoded caller buffer'),
        ('sdl3-font-example', ['sdl3', 'sdl3-ttf'], [font] if font else [], 'rendered text'),
        ('opengl-example', ['sdl3'], ['--smoke'], 'triangle rendered'),
    ]
    try:
        for project, dependencies, arguments, expected in cases:
            if not available(dependencies) or (project == 'sdl3-font-example' and not font):
                message = f'SKIP {project}: missing provider/font'
                print(message, flush=True)
                results.append(dict(project=project, status='skipped', reason=message))
                if options.require_all:
                    raise RuntimeError(message)
                continue
            versions = subprocess.check_output(['pkg-config', '--modversion', *dependencies], env=env, text=True).splitlines()
            for mode in ([], ['--release']):
                binary = work/project
                run([dyn, 'build', f'projects/{project}', '--no-cache', '--quiet', '--output', str(binary), *mode])
                runtime_env = dict(env)
                if project == 'opengl-example':
                    runtime_env['SDL_VIDEODRIVER'] = env.get('DYN_TEST_GL_DRIVER', 'offscreen')
                output = run([str(binary), *arguments], env=runtime_env, capture_output=True, text=True)
                assert expected in output.stdout, output.stdout
                if project == 'archive-example':
                    bad = subprocess.run([str(binary), str(invalid)], env=env, capture_output=True, timeout=10)
                    assert bad.returncode != 0, 'corrupt archive accepted'
                if project == 'curl-example':
                    run([dyn, 'build', 'tests/vendor-packages/curl', '--no-cache', '--quiet', '--output', str(binary), *mode])
                    run([str(binary), url, url + 'missing'])
            print(f'PASS {project}: native debug/release', flush=True)
            results.append(dict(project=project, status='passed', versions=dict(zip(dependencies, versions))))
        if available(['tree-sitter', 'sdl3', 'sdl3-image', 'sdl3-ttf', 'lua5.4', 'libcurl', 'libpcre2-8']) and font:
            oracle = work/'oracle.o'
            flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', 'tree-sitter', 'sdl3', 'sdl3-ttf', 'lua5.4', 'libcurl', 'libpcre2-8'], env=env, text=True))
            run([*shlex.split(env.get('CC', 'cc')), '-std=c11', '-c', 'tests/vendor-packages/abi/oracle.c', *flags, '-o', str(oracle)])
            for mode in ([], ['--release']):
                binary = work/'abi'
                run([dyn, 'build', 'tests/vendor-packages/abi', '--no-cache', '--quiet', '--output', str(binary), '--link', str(oracle), *mode])
                run([str(binary), str(image), font], env=dict(env, SDL_VIDEODRIVER='dummy'))
            print('PASS provider ABI/layout and SDL surface/texture integration', flush=True)
            results.append(dict(project='provider-abi', status='passed'))
    except Exception as error:
        results.append(dict(project='qualification', status='failed', error=str(error)))
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        (ROOT/'build/vendor-package-results.json').write_text(json.dumps(results, indent=2)+'\n')
