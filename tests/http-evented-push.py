#!/usr/bin/env python3
"""Evented server offload and push: run on a thread pool (other requests keep
flowing), pipelining behind a job, SSE streams with publish, WebSocket echo,
ping, fragments, broadcast, close and protocol errors, HEAD, Date, and the
overflow policy (idle eviction, then 503)."""
import base64
import hashlib
import http.client
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
if sys.platform != 'linux':
    print('SKIP evented push test requires Linux')
    raise SystemExit(0)


def expected_hash(body):
    return hashlib.pbkdf2_hmac('sha256', body, bytes(16), 20000, 32).hex().encode() + b'\n'


def request(port, method, path, body=None, headers=None):
    client = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    client.request(method, path, body=body, headers=headers or {})
    reply = client.getresponse()
    data = reply.read()
    result = (reply.status, {k.lower(): v for k, v in reply.getheaders()}, data)
    client.close()
    return result


def read_until(sock, marker, limit=1 << 20):
    data = b''
    while marker not in data:
        chunk = sock.recv(65536)
        if not chunk:
            break
        data += chunk
        assert len(data) < limit
    return data


def ws_connect(port):
    sock = socket.create_connection(('127.0.0.1', port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((f'GET /chat HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                  f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
    head = read_until(sock, b'\r\n\r\n')
    assert head.startswith(b'HTTP/1.1 101 '), head
    accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
    assert b'Sec-WebSocket-Accept: ' + accept in head, head
    return sock, head.split(b'\r\n\r\n', 1)[1]


def ws_frame(opcode, payload, final=True, masked=True):
    first = (0x80 if final else 0) | opcode
    mask = os.urandom(4)
    size = len(payload)
    if size < 126:
        head = struct.pack('!BB', first, (0x80 if masked else 0) | size)
    elif size < 65536:
        head = struct.pack('!BBH', first, (0x80 if masked else 0) | 126, size)
    else:
        head = struct.pack('!BBQ', first, (0x80 if masked else 0) | 127, size)
    if not masked:
        return head + payload
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


class Reader:
    def __init__(self, sock, buffered=b''):
        self.sock, self.buffer = sock, buffered

    def need(self, count):
        while len(self.buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError
            self.buffer += chunk
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    def frame(self):
        first, second = self.need(2)
        assert second & 0x80 == 0, 'server frames are unmasked'
        size = second & 0x7f
        if size == 126:
            size = struct.unpack('!H', self.need(2))[0]
        elif size == 127:
            size = struct.unpack('!Q', self.need(8))[0]
        return first & 0x0f, self.need(size)


def exercise(port):
    status, headers, body = request(port, 'GET', '/health')
    assert (status, body) == (200, b'ok\n')
    assert headers['date'].endswith(' GMT') and len(headers['date']) == 29, headers
    status, headers, body = request(port, 'HEAD', '/health')
    assert (status, body, headers['content-length']) == (200, b'', '3'), (status, body, headers)

    assert request(port, 'GET', '/ip')[2] == b'127.0.0.1'

    # Static assets: gzip when accepted, ETag and Last-Modified revalidation, HEAD.
    css = b'body { color: red; } ' * 196 + b'body'
    status, headers, body = request(port, 'GET', '/static/style.css', headers={'Accept-Encoding': 'gzip'})
    assert (status, headers['content-encoding'], headers['vary']) == (200, 'gzip', 'Accept-Encoding'), headers
    import gzip as gz
    assert gz.decompress(body) == css[:4096] and len(body) < 200
    etag = headers['etag']
    assert headers['last-modified'] == 'Sun, 06 Nov 1994 08:49:37 GMT' and headers['cache-control'] == 'public, max-age=60'
    status, headers, body = request(port, 'GET', '/static/style.css', headers={'Accept-Encoding': 'gzip;q=0'})
    assert (status, 'content-encoding' in headers, body) == (200, False, css[:4096])
    status, headers, body = request(port, 'GET', '/static/style.css', headers={'If-None-Match': f'"x", W/{etag}'})
    assert (status, body, headers['etag'], 'content-length' in headers) == (304, b'', etag, False), headers
    status, _, _ = request(port, 'GET', '/static/style.css', headers={'If-Modified-Since': 'Sun, 06 Nov 1994 08:49:37 GMT'})
    assert status == 304
    status, _, _ = request(port, 'GET', '/static/style.css', headers={'If-Modified-Since': 'Sat, 05 Nov 1994 08:49:37 GMT'})
    assert status == 200
    status, headers, body = request(port, 'HEAD', '/static/logo.png')
    assert (status, body, headers['content-type'], headers['content-length']) == (200, b'', 'image/png', '15'), headers
    assert request(port, 'GET', '/static/missing.js')[0] == 404

    # Offload: the hash runs on the pool and matches Python's PBKDF2.
    status, _, body = request(port, 'POST', '/hash', b'correct horse')
    assert (status, body) == (200, expected_hash(b'correct horse')), body

    # While eight hashes run, health stays fast.
    results = []
    threads = [threading.Thread(target=lambda i=i: results.append(request(port, 'POST', '/hash', b'p%d' % i)))
               for i in range(8)]
    for t in threads:
        t.start()
    time.sleep(0.005)
    began = time.perf_counter()
    for _ in range(20):
        assert request(port, 'GET', '/health')[0] == 200
    health_ms = (time.perf_counter() - began) * 1000 / 20
    for t in threads:
        t.join()
    assert sorted(r[2] for r in results) == sorted(expected_hash(b'p%d' % i) for i in range(8))
    assert health_ms < 50, f'health took {health_ms:.1f} ms during jobs'

    # A pipelined request behind a job is answered after it, in order.
    with socket.create_connection(('127.0.0.1', port), timeout=10) as sock:
        sock.sendall(b'POST /hash HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\n\r\nab'
                     b'GET /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n')
        data = b''
        while chunk := sock.recv(65536):
            data += chunk
        first = data.index(expected_hash(b'ab'))
        assert data.index(b'ok\n') > first, data

    # SSE: hello on connect, then published events.
    streams = []
    for _ in range(2):
        sock = socket.create_connection(('127.0.0.1', port), timeout=10)
        sock.sendall(b'GET /events HTTP/1.1\r\nHost: x\r\n\r\n')
        data = read_until(sock, b'data: connected\n\n')
        assert b'Content-Type: text/event-stream' in data and b'Transfer-Encoding: chunked' in data, data
        streams.append(sock)

    # WebSocket: echo text and binary, ping, fragments.
    one, rest = ws_connect(port)
    reader = Reader(one, rest)
    one.sendall(ws_frame(1, b'hello'))
    assert reader.frame() == (1, b'echo:hello')
    one.sendall(ws_frame(2, b'\x00\x01\xff'))
    assert reader.frame() == (2, b'echo:\x00\x01\xff')
    one.sendall(ws_frame(9, b'are you there'))
    assert reader.frame() == (10, b'are you there')
    one.sendall(ws_frame(1, b'frag', final=False) + ws_frame(9, b'p') + ws_frame(0, b'men', final=False) + ws_frame(0, b'ted'))
    assert reader.frame() == (10, b'p')
    assert reader.frame() == (1, b'echo:fragmented')
    big = bytes(range(256)) * 12
    one.sendall(ws_frame(2, big[:1000], final=False))
    one.sendall(ws_frame(0, big[1000:]))
    assert reader.frame() == (2, b'echo:' + big)
    one.sendall(ws_frame(1, 'héllo ✓'.encode()))
    assert reader.frame() == (1, 'echo:héllo ✓'.encode())

    two, rest_two = ws_connect(port)
    reader_two = Reader(two, rest_two)
    # Broadcast from a socket and from an HTTP request reach every socket and stream.
    one.sendall(ws_frame(1, b'all:hi everyone'))
    assert reader.frame() == (1, b'hi everyone')
    assert reader_two.frame() == (1, b'hi everyone')
    status, _, body = request(port, 'POST', '/broadcast', b'line one\nline two')
    assert (status, body) == (200, b'sent\n')
    assert reader.frame() == (1, b'line one\nline two')
    assert reader_two.frame() == (1, b'line one\nline two')
    for sock in streams:
        data = read_until(sock, b'data: line two\n\n')
        assert b'event: message\nid: 7\ndata: line one\ndata: line two\n\n' in data, data

    # Server-initiated close, and a protocol error (unmasked client frame).
    two.sendall(ws_frame(1, b'bye'))
    assert reader_two.frame() == (8, b'\x03\xe8')
    two.close()
    one.sendall(ws_frame(1, b'oops', masked=False))
    assert reader.frame() == (8, struct.pack('!H', 1002))
    one.close()
    # A client close is echoed.
    three, rest_three = ws_connect(port)
    reader_three = Reader(three, rest_three)
    three.sendall(ws_frame(8, struct.pack('!H', 1000)))
    assert reader_three.frame()[0] == 8
    three.close()
    for sock in streams:
        sock.close()

    status, _, body = request(port, 'GET', '/chat')
    assert status == 400, status

    # Overflow: 16 slots. Idle keep-alive connections are evicted for new ones.
    idle = []
    for _ in range(40):
        client = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        client.request('GET', '/health')
        assert client.getresponse().read() == b'ok\n'
        idle.append(client)
        # Eviction takes connections idle at least 200 ms (the test's threshold).
        if len(idle) % 8 == 0:
            time.sleep(0.25)
    assert request(port, 'GET', '/health')[0] == 200
    for client in idle:
        client.close()
    time.sleep(0.2)
    # Every slot holding a stream: a new client gets 503 at once.
    held = []
    for _ in range(16):
        sock = socket.create_connection(('127.0.0.1', port), timeout=10)
        sock.sendall(b'GET /events HTTP/1.1\r\nHost: x\r\n\r\n')
        read_until(sock, b'data: connected\n\n')
        held.append(sock)
    began = time.perf_counter()
    status, headers, body = request(port, 'GET', '/health')
    assert (status, body, headers.get('retry-after')) == (503, b'server busy\n', '1'), (status, body)
    assert time.perf_counter() - began < 1
    for sock in held:
        sock.close()
    time.sleep(0.2)
    assert request(port, 'GET', '/health')[0] == 200


def exercise_wait(port):
    # Overflow.Wait: with every slot holding a stream, a new client is parked,
    # unread, then served as soon as a stream closes.
    held = []
    for _ in range(16):
        sock = socket.create_connection(('127.0.0.1', port), timeout=10)
        sock.sendall(b'GET /events HTTP/1.1\r\nHost: x\r\n\r\n')
        read_until(sock, b'data: connected\n\n')
        held.append(sock)
    waiting = socket.create_connection(('127.0.0.1', port), timeout=10)
    waiting.sendall(b'GET /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n')
    waiting.settimeout(0.5)
    try:
        early = waiting.recv(100)
    except socket.timeout:
        early = None
    assert early is None, early
    held.pop().close()
    waiting.settimeout(10)
    assert read_until(waiting, b'ok\n').startswith(b'HTTP/1.1 200 OK'), 'parked client served'
    waiting.close()
    for sock in held:
        sock.close()


with tempfile.TemporaryDirectory(prefix='dyn-evented-push-') as temporary:
    for mode in ('--debug', '--release'):
        binary = Path(temporary) / 'push'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/http-evented-push'), mode, '--quiet', '--no-cache',
                        '--output', str(binary)], check=True, timeout=180)
        server = subprocess.Popen([str(binary)], stdout=subprocess.PIPE, text=True)
        try:
            line = server.stdout.readline()
            assert line.startswith('port '), line
            exercise(int(line.split()[1]))
            assert request(int(line.split()[1]), 'POST', '/quit')[0] == 200
            summary = server.stdout.readline()
            assert server.wait(timeout=20) == 0
            evicted, refused = int(summary.split()[1]), int(summary.split()[3])
            assert evicted >= 24 and refused >= 1, summary
        finally:
            if server.poll() is None:
                server.kill()
        server = subprocess.Popen([str(binary), 'wait'], stdout=subprocess.PIPE, text=True)
        try:
            port = int(server.stdout.readline().split()[1])
            exercise_wait(port)
            assert request(port, 'POST', '/quit')[0] == 200
            server.stdout.readline()
            assert server.wait(timeout=20) == 0
        finally:
            if server.poll() is None:
                server.kill()
print('evented push ok')
