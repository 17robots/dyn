#!/usr/bin/env python3
"""HTTPS through the evented server's OpenSSL transport: keep-alive, pipelining
inside TLS, large responses to slow readers, concurrent clients, plain HTTP and
garbage refused, idle handshakes closed, clean shutdown."""
import http.client
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
if sys.platform != 'linux' or not shutil.which('openssl'):
    print('SKIP evented HTTPS requires Linux and the openssl command')
    raise SystemExit(0)
BIG = bytes(ord('a') + i % 26 for i in range(200 * 1024))


def exercise(port, certificate):
    context = ssl.create_default_context(cafile=str(certificate))

    def connect():
        return http.client.HTTPSConnection('127.0.0.1', port, timeout=10, context=context)

    client = connect()
    for _ in range(3):
        client.request('GET', '/health')
        reply = client.getresponse()
        assert (reply.status, reply.read()) == (200, b'ok\n')
    client.request('POST', '/echo', body=b'x' * 3000)
    assert client.getresponse().read() == b'x' * 3000
    client.request('GET', '/big')
    assert client.getresponse().read() == BIG
    client.close()

    # Pipelined requests inside one TLS stream, and a slow reader of /big.
    with socket.create_connection(('127.0.0.1', port), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname='127.0.0.1') as tls:
            tls.sendall(b'GET /health HTTP/1.1\r\nHost: x\r\n\r\n' * 3 +
                        b'GET /big HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n')
            time.sleep(0.2)
            received = b''
            while chunk := tls.recv(65536):
                received += chunk
            assert received.count(b'HTTP/1.1 200 OK') == 4 and received.endswith(BIG), len(received)

    # Plain HTTP and garbage on the TLS port get no HTTP response.
    for probe in (b'GET /health HTTP/1.1\r\nHost: x\r\n\r\n', b'\x16\x03\x01\x00\x05hello'):
        with socket.create_connection(('127.0.0.1', port), timeout=10) as raw:
            raw.sendall(probe)
            try:
                reply = raw.recv(1024)
            except ConnectionResetError:
                reply = b''
            assert b'HTTP/1.1' not in reply, reply

    # A client that connects but never starts the handshake is closed.
    with socket.create_connection(('127.0.0.1', port), timeout=10) as raw:
        started = time.monotonic()
        assert raw.recv(1) == b''
        assert time.monotonic() - started < 5

    failures = []

    def worker(index):
        try:
            connection = connect()
            for number in range(50):
                body = f'{index}-{number}'.encode()
                connection.request('POST', '/echo', body=body)
                reply = connection.getresponse()
                if (reply.status, reply.read()) != (200, body):
                    failures.append((index, number))
            connection.close()
        except Exception as error:
            failures.append(repr(error))

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(24)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not failures, failures[:5]

    client = connect()
    client.request('POST', '/quit')
    assert client.getresponse().status == 200
    client.close()


with tempfile.TemporaryDirectory(prefix='dyn-http-tls-') as temporary:
    work = Path(temporary)
    certificate = work / 'cert.pem'
    key = work / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes',
                    '-days', '2', '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1',
                    '-keyout', str(key), '-out', str(certificate)], check=True, capture_output=True, timeout=60)
    for release in (False, True):
        program = work / 'server'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/http-evented-tls'), '--no-cache', '--quiet',
                        '--output', str(program)] + (['--release'] if release else []), check=True, timeout=300)
        server = subprocess.Popen([str(program), str(certificate), str(key)], stdout=subprocess.PIPE)
        try:
            line = server.stdout.readline().decode()
            assert line.startswith('port '), line
            exercise(int(line.split()[1]), certificate)
            assert server.wait(timeout=15) == 0
        finally:
            if server.poll() is None:
                server.kill()
                server.wait()
print('PASS evented HTTPS: keep-alive, pipelining, slow large responses, 24 clients, plain/garbage refused, idle handshake closed (debug/release)')
