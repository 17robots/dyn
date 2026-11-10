#!/usr/bin/env python3
"""Evented HTTP server: keep-alive, pipelining, byte-split requests, large
responses to slow readers, chunked streams, 400/413, idle timeout, many clients."""
import http.client
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
if sys.platform != 'linux':
    print('SKIP evented HTTP server test requires Linux')
    raise SystemExit(0)
BIG = bytes(ord('a') + i % 26 for i in range(200 * 1024))


def read_all(connection):
    received = b''
    while chunk := connection.recv(65536):
        received += chunk
    return received


def raw(port, data):
    with socket.create_connection(('127.0.0.1', port), timeout=10) as connection:
        connection.sendall(data)
        return read_all(connection)


def exercise(port):
    client = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    for _ in range(3):
        client.request('GET', '/health')
        reply = client.getresponse()
        assert (reply.status, reply.read()) == (200, b'ok\n')
    client.request('GET', '/missing')
    reply = client.getresponse()
    assert (reply.status, reply.read()) == (404, b'not found\n')
    client.request('POST', '/echo', body=b'x' * 3000)
    reply = client.getresponse()
    assert (reply.status, reply.read()) == (200, b'x' * 3000)
    client.request('GET', '/stream')
    reply = client.getresponse()
    assert (reply.status, reply.read()) == (200, b'chunk\n' * 3)
    # Response far larger than the 4 KiB send buffer, same connection after.
    client.request('GET', '/big')
    reply = client.getresponse()
    assert (reply.status, reply.read()) == (200, BIG)
    client.request('GET', '/health')
    assert client.getresponse().read() == b'ok\n'
    client.close()

    # Slow reader: the worker drains the large body as the peer reads.
    with socket.create_connection(('127.0.0.1', port), timeout=10) as connection:
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        connection.sendall(b'GET /big HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n')
        time.sleep(0.2)
        received = read_all(connection)
        assert received.endswith(BIG), len(received)

    # Pipelining, in one write and split byte by byte.
    pipeline = (b'GET /health HTTP/1.1\r\nHost: x\r\n\r\n' * 3 +
                b'GET /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n')
    assert raw(port, pipeline).count(b'HTTP/1.1 200 OK') == 4
    with socket.create_connection(('127.0.0.1', port), timeout=10) as connection:
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        for byte in pipeline:
            connection.sendall(bytes([byte]))
        assert read_all(connection).count(b'HTTP/1.1 200 OK') == 4

    # Invalid and oversized requests are answered, then closed.
    assert raw(port, b'NOT HTTP\r\n\r\n').startswith(b'HTTP/1.1 400 Bad Request\r\n')
    huge_body = b'POST /echo HTTP/1.1\r\nHost: x\r\nContent-Length: 100000\r\n\r\n'
    assert raw(port, huge_body).startswith(b'HTTP/1.1 413 Payload Too Large\r\n')
    huge_head = b'GET /health HTTP/1.1\r\nX-Fill: ' + b'y' * 8000 + b'\r\n\r\n'
    assert raw(port, huge_head).startswith(b'HTTP/1.1 413 Payload Too Large\r\n')
    chunked = b'POST /echo HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n'
    assert raw(port, chunked).startswith(b'HTTP/1.1 400 Bad Request\r\n')

    # Idle connections close after the 500 ms timeout.
    with socket.create_connection(('127.0.0.1', port), timeout=10) as connection:
        started = time.monotonic()
        assert connection.recv(1) == b''
        assert 0.3 < time.monotonic() - started < 5

    # More concurrent keep-alive clients (48) than the 32 slots: extras wait in the backlog.
    failures = []

    def client_thread(index):
        try:
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            for number in range(100):
                body = f'{index}-{number}'.encode()
                connection.request('POST', '/echo', body=body)
                reply = connection.getresponse()
                if (reply.status, reply.read()) != (200, body):
                    failures.append((index, number))
            connection.close()
        except Exception as error:
            failures.append(repr(error))

    threads = [threading.Thread(target=client_thread, args=(index,)) for index in range(48)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not failures, failures[:5]

    client = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    client.request('POST', '/quit')
    assert client.getresponse().status == 200
    client.close()


with tempfile.TemporaryDirectory(prefix='dyn-http-evented-') as temporary:
    for release in (False, True):
        program = Path(temporary) / 'server'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/http-evented'), '--no-cache', '--quiet',
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
print('PASS evented HTTP: keep-alive, pipelining, byte splits, large/slow/streamed responses, 400/413, idle timeout, 48 clients over 32 slots (debug/release)')
