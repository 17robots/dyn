#!/usr/bin/env python3
"""Install an unpublished SDK through mise's HTTP backend, then compile and run."""
import argparse
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('archive', type=Path)
parser.add_argument('--version', required=True)
args = parser.parse_args()
archive = args.archive.resolve()
class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass
server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(archive.parent)))
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with tempfile.TemporaryDirectory(prefix='dyn-mise-package-') as temporary:
        work = Path(temporary)
        config = {'version': args.version, 'url': f'http://127.0.0.1:{server.server_port}/{archive.name}',
                  'checksum': 'sha256:'+hashlib.sha256(archive.read_bytes()).hexdigest(),
                  'strip_components': 1, 'bin_path': 'bin'}
        import json
        (work/'mise.toml').write_text('[tools."http:dyn-candidate"]\n'+''.join(f'{k} = {json.dumps(v)}\n' for k,v in config.items()))
        env = dict(os.environ, MISE_DATA_DIR=str(work/'data'), MISE_CACHE_DIR=str(work/'cache'),
                   MISE_CONFIG_DIR=str(work/'config'), MISE_TRUSTED_CONFIG_PATHS=str(work))
        env.pop('DYN_SDK',None)
        def run(*command):
            result = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=180)
            if result.returncode:
                raise RuntimeError(f'{command!r} failed: {result.stdout}\n{result.stderr}')
            return result
        run('mise','install')
        actual = run('mise','exec','--','dyn','version').stdout.strip()
        if actual != 'dyn '+args.version:
            raise RuntimeError('Installed version mismatch: '+actual)
        run('mise','exec','--','dyn','build',str(ROOT/'compiler/tests/smoke'),
            '--release','--no-cache','--quiet','--output',str(work/'smoke'))
        run(str(work/'smoke'))
        print('PASS mise candidate installation, version, compilation and execution')
finally:
    server.shutdown()
    server.server_close()
    thread.join()
