#!/usr/bin/env python3
"""An evented server with the default Config (1024 connection slots and a job
arena per slot, on each of four workers) keeps idle slots untouched: slots
are set up when first taken, job arenas on the first job, and the worker's
storage comes from arena_from_zeroed, so pushes skip zeroing fresh pages.
After serving keep-alive requests, the flagship server stays under 2 MiB
resident (it was about 9.7 MiB)."""
import http.client
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())


def peak_kib(pid):
    for line in Path(f'/proc/{pid}/status').read_text().splitlines():
        if line.startswith('VmHWM:'):
            return int(line.split()[1])
    raise AssertionError('no VmHWM')


with tempfile.TemporaryDirectory(prefix='dyn-http-idle-memory-') as temporary:
    program = Path(temporary) / 'server'
    subprocess.run([DYN, 'build', str(ROOT / 'tests/flagship-http'), '--release', '--quiet', '--no-cache',
                    '--output', str(program)], check=True, timeout=180)
    server = subprocess.Popen([str(program)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        port = int(server.stdout.readline().decode().split()[1])
        for _ in range(4):
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            for _ in range(50):
                connection.request('GET', '/health')
                response = connection.getresponse()
                assert response.status == 200, response.status
                response.read()
            connection.close()
        peak = peak_kib(server.pid)
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        connection.request('POST', '/quit')
        connection.getresponse().read()
        server.wait(timeout=20)
    finally:
        if server.poll() is None:
            server.kill()
    assert peak < 2048, peak
print(f'PASS evented server idle memory: {peak} KiB resident after 200 requests (default Config, four workers)')
