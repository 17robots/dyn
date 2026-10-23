#!/usr/bin/env python3
"""Flagship HTTP service: concurrent notes server driven by real clients."""
import http.client
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
if sys.platform != 'linux':
    print('SKIP flagship HTTP server requires Linux worker threads')
    raise SystemExit(0)


def raw(port, data):
    with socket.create_connection(('127.0.0.1', port), timeout=10) as connection:
        connection.sendall(data)
        received = b''
        while chunk := connection.recv(65536):
            received += chunk
        return received


def exercise(port):
    client = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    client.request('GET', '/health')
    reply = client.getresponse()
    assert (reply.status, reply.read()) == (200, b'ok\n')
    # Keep-alive: the same connection serves several requests.
    client.request('GET', '/missing')
    reply = client.getresponse()
    assert (reply.status, reply.read()) == (404, b'not found\n')
    client.request('POST', '/notes', body=b'two\nlines')
    reply = client.getresponse()
    assert reply.status == 400, reply.status
    reply.read()
    client.close()

    failures = []

    def writer(index):
        try:
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            for number in range(25):
                connection.request('POST', '/notes', body=f'note {index}-{number}'.encode())
                response = connection.getresponse()
                if response.status != 200:
                    failures.append(response.status)
                response.read()
            connection.close()
        except Exception as error:  # Report thread failures in the main thread.
            failures.append(repr(error))

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not failures, failures
    client = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    client.request('GET', '/notes')
    reply = client.getresponse()
    lines = reply.read().decode().splitlines()
    expected = {f'note {index}-{number}' for index in range(8) for number in range(25)}
    assert reply.status == 200 and len(lines) == 200 and set(lines) == expected, len(lines)
    client.close()

    # Pipelined requests in one write are answered in order.
    pipelined = raw(port, b'GET /health HTTP/1.1\r\nHost: x\r\n\r\n'
                          b'GET /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n')
    assert pipelined.count(b'HTTP/1.1 200 OK') == 2, pipelined
    # Malformed and oversized requests get a reply before the connection closes.
    assert raw(port, b'NOT HTTP\r\n\r\n').startswith(b'HTTP/1.1 400 Bad Request\r\n')
    huge = b'POST /notes HTTP/1.1\r\nHost: x\r\nContent-Length: 100000\r\n\r\n'
    assert raw(port, huge).startswith(b'HTTP/1.1 413 Payload Too Large\r\n')

    client = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    client.request('POST', '/quit')
    assert client.getresponse().status == 200
    client.close()


with tempfile.TemporaryDirectory(prefix='dyn-flagship-http-') as temporary:
    for release in (False, True):
        program = Path(temporary) / 'server'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/flagship-http'), '--no-cache', '--quiet',
                        '--output', str(program)] + (['--release'] if release else []),
                       check=True, timeout=120)
        server = subprocess.Popen([str(program)], stdout=subprocess.PIPE)
        try:
            line = server.stdout.readline().decode()
            assert line.startswith('port '), line
            exercise(int(line.split()[1]))
            assert server.wait(timeout=15) == 0
        finally:
            if server.poll() is None:
                server.kill()
                server.wait()
print('PASS flagship HTTP notes server: routing, keep-alive, pipelining, 400/413, 8 concurrent clients (debug/release)')
