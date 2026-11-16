#!/usr/bin/env python3
"""evented.serve answers requests, then stops cleanly on SIGTERM and SIGINT;
Config.access_log writes one line per request, and Config.slow_handler_microseconds
warns about a slow handler."""
import re
import http.client
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
if sys.platform != 'linux':
    print('SKIP evented.serve test requires Linux')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-http-serve-') as temporary:
    program = Path(temporary) / 'serve'
    subprocess.run([DYN, 'build', str(ROOT / 'tests/http-serve'), '--quiet', '--no-cache', '--output', str(program)],
                   check=True, timeout=180)
    for sent in (signal.SIGTERM, signal.SIGINT):
        server = subprocess.Popen([str(program)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(100):
                try:
                    client = http.client.HTTPConnection('127.0.0.1', 18097, timeout=5)
                    client.request('GET', '/')
                    reply = client.getresponse()
                    break
                except ConnectionRefusedError:
                    time.sleep(0.05)
            assert (reply.status, reply.read()) == (200, b'hello\n')
            client.request('GET', '/slow')
            reply = client.getresponse()
            assert (reply.status, reply.read()) == (200, b'hello\n')
            client.close()
            server.send_signal(sent)
            assert server.wait(timeout=10) == 0
            assert server.stdout.read() == 'stopped 2\n'
            logged = server.stderr.read()
            assert re.fullmatch(r'info: request client=127\.0\.0\.1 method=GET path=/ status=200 us=\d+\n'
                                r'warning: slow handler method=GET path=/slow us=\d+\n'
                                r'info: request client=127\.0\.0\.1 method=GET path=/slow status=200 us=\d+\n', logged), logged
        finally:
            if server.poll() is None:
                server.kill()
                server.wait()
print('PASS evented.serve: answers, logs, stops on SIGTERM and SIGINT')
