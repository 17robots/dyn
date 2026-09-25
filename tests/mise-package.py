#!/usr/bin/env python3
"""Install an unpublished SDK through mise's HTTP backend, then compile and run."""
import argparse
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
import shutil
import sys
import json
from pathlib import Path
import subprocess
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('archive', type=Path)
parser.add_argument('--version', required=True)
parser.add_argument('--report', type=Path)
args = parser.parse_args()
archive = args.archive.resolve()
mise = shutil.which('mise')
if not mise: raise SystemExit('mise is required')
if args.report:
    report = json.loads(args.report.read_text())
    if report['version'] != args.version or report['sha256'] != hashlib.sha256(archive.read_bytes()).hexdigest():
        raise SystemExit('Candidate does not match package report')
    report['status'] = 'testing'
    args.report.write_text(json.dumps(report,indent=2)+'\n')
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
        (work/'mise.toml').write_text('[tools."http:dyn-candidate"]\n'+''.join(f'{k} = {json.dumps(v)}\n' for k,v in config.items()))
        env = dict(os.environ, MISE_DATA_DIR=str(work/'data'), MISE_CACHE_DIR=str(work/'cache'),
                   MISE_CONFIG_DIR=str(work/'config'), MISE_TRUSTED_CONFIG_PATHS=str(work))
        env.pop('DYN_SDK',None)
        for key in ('LD_LIBRARY_PATH','DYLD_LIBRARY_PATH','DYLD_FALLBACK_LIBRARY_PATH','ZIG_LIB_DIR'):
            env.pop(key,None)
        # Toolchains used to build the archive must not satisfy missing dependencies.
        env['PATH'] = os.pathsep.join([str(Path(os.environ['SystemRoot'])/'System32'),os.environ['SystemRoot']]) if os.name == 'nt' else '/usr/bin:/bin:/usr/sbin:/sbin'
        env['DYN_CACHE_DIR'] = str(work/'dyn-cache')
        def run(*command):
            result = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=180)
            if result.returncode:
                raise RuntimeError(f'{command!r} failed: {result.stdout}\n{result.stderr}')
            return result
        run(mise,'install')
        actual = run(mise,'exec','--','dyn','version').stdout.strip()
        if actual != 'dyn '+args.version:
            raise RuntimeError('Installed version mismatch: '+actual)
        installed = Path(run(mise,'where','http:dyn-candidate').stdout.strip())
        manifest = json.loads((installed/'manifest.json').read_text())
        for name, digest in manifest['files'].items():
            if hashlib.sha256((installed/name).read_bytes()).hexdigest() != digest:
                raise RuntimeError('Installed file hash mismatch: '+name)
        project = work/'project with spaces'
        shutil.copytree(ROOT/'tests/smoke',project)
        output = work/('smoke.exe' if os.name == 'nt' else 'smoke')
        for options in ([], ['--release']):
            run(mise,'exec','--','dyn','build',str(project), '--no-cache','--quiet','--output',str(output), *options)
            run(str(output))
        env['DYN'] = str(installed/'bin'/('dyn.exe' if os.name == 'nt' else 'dyn'))
        run(sys.executable, str(ROOT/'tests/stdlib-host.py'))
        if args.report:
            report.update(status='passed',mise=True,isolated_path=True)
            args.report.write_text(json.dumps(report,indent=2)+'\n')
        print('PASS mise candidate installation, version, compilation and execution')
finally:
    server.shutdown()
    server.server_close()
    thread.join()
