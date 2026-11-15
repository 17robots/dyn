#!/usr/bin/env python3
"""HTTP/2 on the evented server (prior knowledge), through tests/h2client.py:
requests and HEAD, bodies in slots, upload blocks and on_large_body, gzip,
flow control with 64 KiB windows, multiplexing past slow run jobs, SSE with
publish, trailers, CONTINUATION, PING, client resets, malformed requests and
connection errors. HTTP/1.1 keeps working on the same port."""
import gzip
import http.client
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import h2client  # noqa: E402
from h2client import Client, DATA, HEADERS, RST, SETTINGS, PING, GOAWAY, WINDOW, CONTINUATION, literal  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
if sys.platform != 'linux':
    print('SKIP HTTP/2 test requires Linux')
    raise SystemExit(0)
BIG = bytes(ord('a') + i % 26 for i in range(300 * 1024))


def goaway(client):
    """Reads until GOAWAY or close; the error code, or None."""
    try:
        while True:
            kind, _, _, payload = client.read_frame()
            if kind == GOAWAY:
                return struct.unpack('!II', payload[:8])[1]
    except (EOFError, ConnectionResetError):
        return None


def exercise(port):
    c = Client(port)
    status, headers, body = c.response(c.request('GET', '/health'))
    assert (status, body, headers['content-type'], headers['date'][-3:]) == (200, b'ok\n', 'text/plain', 'GMT'), headers
    assert c.settings[3] == 100 and c.settings[4] == 1048576, c.settings
    stream = c.request('HEAD', '/health')
    status, headers, body = c.response(stream)
    assert (status, body, headers['content-length']) == (200, b'', '3'), headers
    assert not any(f[0] == DATA and f[2] == stream for f in c.frames), 'HEAD sends no DATA'
    status, _, body = c.response(c.request('POST', '/upload', b'small'))
    assert body == b'5 %d' % sum(b'small'), body
    blob = bytes((i * 7) % 251 for i in range(700 * 1024))
    status, _, body = c.response(c.request('POST', '/upload', blob, headers=[('content-length', str(len(blob)))]))
    assert (status, body) == (200, b'%d %d' % (len(blob), sum(blob))), (status, body)
    large = bytes((i * 13) % 256 for i in range(3 * 1024 * 1024 + 5))
    status, _, body = c.response(c.request('POST', '/large', large))
    assert (status, body) == (200, b'%d %d' % (len(large), sum(large))), (status, body)
    stream = c.request('POST', '/large?limit=1000000', large)
    status, _, body = c.response(stream)
    assert status == 413 and body.startswith(b'stopped after '), (status, body)
    status, headers, body = c.response(c.request('GET', '/report', headers=[('accept-encoding', 'gzip')]))
    assert headers['content-encoding'] == 'gzip' and gzip.decompress(body).startswith(b'[{"id":0'), headers
    # Responses past the client's 64 KiB windows wait for WINDOW_UPDATE.
    for _ in range(3):
        status, _, body = c.response(c.request('GET', '/big'))
        assert (status, body) == (200, BIG), (status, len(body))
    ids = [c.request('GET', '/big?n=%d' % i) for i in range(12)]
    assert all(c.response(s)[2] == BIG for s in ids)
    # PING is echoed.
    c.send(PING, 0, 0, b'12345678')
    while not any(f[0] == PING and f[1] & 1 for f in c.frames):
        c.read_frame()
    # A header block split across CONTINUATION frames.
    block = literal(':method', 'GET') + literal(':scheme', 'http') + literal(':path', '/health') + literal(':authority', 't')
    stream = c.next_id
    c.next_id += 2
    c.streams[stream] = {'headers': None, 'data': b'', 'ended': False, 'reset': None}
    c.send(HEADERS, 0x1, stream, block[:7])
    c.send(CONTINUATION, 0, stream, block[7:20])
    c.send(CONTINUATION, 0x4, stream, block[20:])
    assert c.response(stream)[2] == b'ok\n'
    # Trailers end a request body.
    stream = c.request('POST', '/upload', b'abc', end=False)
    c.send(HEADERS, 0x5, stream, literal('x-checksum', '1'))
    assert c.response(stream)[2] == b'3 %d' % sum(b'abc')
    # Malformed requests are reset with PROTOCOL_ERROR; the connection lives.
    for extra in ([('Bad-Case', 'x')], [('connection', 'keep-alive')], [('te', 'gzip')], [('x', ' padded')]):
        stream = c.request('GET', '/health', headers=extra)
        assert c.wait(stream)['reset'] == 1, extra
    stream = c.request('POST', '/upload', b'abcd', headers=[('content-length', '9')])
    assert c.wait(stream)['reset'] == 1, 'content-length mismatch'
    assert c.response(c.request('GET', '/health'))[2] == b'ok\n'
    c.close()

    # Slow jobs do not hold up other streams on the same connection.
    c = Client(port)
    hashes = [c.request('POST', '/hash', b'p%d' % i) for i in range(4)]
    quick = c.request('GET', '/health')
    c.wait(quick)
    pending = [s for s in hashes if not c.streams[s]['ended']]
    assert pending, 'health answered while jobs ran'
    for s in hashes:
        status, _, body = c.response(s)
        assert status == 200 and len(body) == 65, (status, body)
    # SSE: a push stream stays open; broadcast reaches it; a client reset ends it.
    events = c.request('GET', '/events')
    while b'connected' not in c.streams[events]['data']:
        c.read_frame()
    assert dict(c.streams[events]['headers'])['content-type'] == 'text/event-stream'
    assert c.response(c.request('POST', '/broadcast', b'over h2'))[2] == b'sent\n'
    while b'data: over h2' not in c.streams[events]['data']:
        c.read_frame()
    assert not c.streams[events]['ended']
    c.send(RST, 0, events, struct.pack('!I', 8))
    # A client reset mid-response: the server moves on.
    c.auto_window = False
    big = c.request('GET', '/big')
    while len(c.streams[big]['data']) < 16384:
        c.read_frame()
    c.send(RST, 0, big, struct.pack('!I', 8))
    c.auto_window = True
    c.send(WINDOW, 0, 0, struct.pack('!I', 1 << 20))
    assert c.response(c.request('GET', '/health'))[2] == b'ok\n'
    c.close()

    # Connection errors: GOAWAY, then close.
    for frames, code in (('badsettings', 6), (None, 1), ('data0', 1), ('bigframe', 6)):
        c = Client.__new__(Client)
        import socket
        c.sock = socket.create_connection(('127.0.0.1', port), timeout=10)
        c.buffer, c.frames, c.streams, c.settings, c.auto_window = b'', [], {}, {}, False
        c.decoder = h2client.Decoder()
        if frames is None:
            # The first frame must be SETTINGS.
            c.sock.sendall(h2client.PREFACE + Client.frame(PING, 0, 0, b'12345678'))
        elif frames == 'data0':
            c.sock.sendall(h2client.PREFACE + Client.frame(SETTINGS, 0, 0, b'') + Client.frame(DATA, 0, 0, b'x'))
        elif frames == 'badsettings':
            c.sock.sendall(h2client.PREFACE + Client.frame(SETTINGS, 0, 0, b'12345'))
        elif frames == 'bigframe':
            c.sock.sendall(h2client.PREFACE + Client.frame(SETTINGS, 0, 0, b'') + b'\x00\x50\x00' + bytes([DATA, 0]) +
                           struct.pack('!I', 1))
        else:
            c.sock.sendall(frames)
        assert goaway(c) == code, frames
        c.sock.close()

    # HTTP/1.1 on the same port.
    client = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    client.request('GET', '/health')
    assert client.getresponse().read() == b'ok\n'
    client.close()


with tempfile.TemporaryDirectory(prefix='dyn-h2-') as temporary:
    binary = Path(temporary) / 'push'
    for mode in ('--debug', '--release'):
        subprocess.run([DYN, 'build', str(ROOT / 'tests/http-evented-push'), mode, '--quiet', '--no-cache',
                        '--output', str(binary)], check=True, timeout=180)
        server = subprocess.Popen([str(binary), 'h2'], stdout=subprocess.PIPE, text=True)
        try:
            line = server.stdout.readline()
            assert line.startswith('port '), line
            port = int(line.split()[1])
            exercise(port)
            client = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            client.request('POST', '/quit')
            client.getresponse().read()
            assert server.wait(timeout=20) == 0
        finally:
            if server.poll() is None:
                server.kill()
                server.wait()
print('PASS HTTP/2: requests, HEAD, bodies, uploads, large bodies, gzip, flow control, multiplexed jobs, SSE, '
      'trailers, CONTINUATION, PING, resets, malformed requests, connection errors (debug/release)')
