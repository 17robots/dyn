#!/usr/bin/env python3
"""evented.job with a type larger than Config.job_size panics with the type,
both sizes and the fix, instead of returning nil on every request."""
import os
from pathlib import Path
import socket
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-http-job-size-') as temporary:
    program = Path(temporary) / 'server'
    subprocess.run([DYN, 'build', str(ROOT / 'tests/http-job-size'), '--quiet', '--no-cache', '--output', str(program)],
                   check=True, timeout=180)
    server = subprocess.Popen([str(program)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        port = int(server.stdout.readline().split()[1])
        with socket.create_connection(('127.0.0.1', port), timeout=10) as client:
            client.sendall(b'GET / HTTP/1.1\r\nHost: x\r\n\r\n')
            try:
                client.recv(100)
            except OSError:
                pass
        _, stderr = server.communicate(timeout=30)
    finally:
        if server.poll() is None:
            server.kill()
    assert server.returncode == 101, (server.returncode, stderr)
    assert 'evented.job: Big needs 4096 bytes, but Config.job_size is 1024; raise job_size' in stderr, stderr
print('PASS evented.job: a job type larger than Config.job_size panics with the sizes')
