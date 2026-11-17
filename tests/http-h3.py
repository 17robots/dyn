#!/usr/bin/env python3
"""HTTP/3 on the evented server through OpenSSL QUIC, driven by curl's HTTP/3
client (ngtcp2 and nghttp3): requests, HEAD, bodies in slots, upload blocks
and on_large_body, gzip, many streams on one connection, run jobs, SSE with
publish, Alt-Svc on TCP responses and connection slots given back."""
import gzip
import http.client
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
curl = shutil.which('curl')
features = subprocess.run([curl, '-V'], capture_output=True, text=True).stdout if curl else ''
if sys.platform != 'linux' or 'HTTP3' not in features or not shutil.which('openssl'):
    print('SKIP HTTP/3 test requires Linux, openssl and curl with HTTP3')
    raise SystemExit(0)


def h3(port, certificate, path, *extra, binary=True):
    command = [curl, '-s', '--http3-only', '--cacert', str(certificate), '--max-time', '30', *extra,
               f'https://127.0.0.1:{port}{path}']
    return subprocess.run(command, capture_output=True, check=True, timeout=60).stdout


def exercise(port, certificate, work):
    out = h3(port, certificate, '/health', '-w', '\n%{http_version} %{http_code}')
    assert out == b'ok\n\n3 200', out
    head = h3(port, certificate, '/health', '-I').decode().replace('\r', '')
    assert head.startswith('HTTP/3 200') and 'content-length: 3' in head, head
    # TCP responses tell browsers where HTTP/3 is.
    client = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    client.request('GET', '/health')
    reply = client.getresponse()
    assert reply.read() == b'ok\n' and reply.getheader('alt-svc') == f'h3=":{port}"; ma=86400', reply.getheaders()
    client.close()
    blob = bytes((i * 7) % 251 for i in range(700 * 1024))
    (work / 'mid.bin').write_bytes(blob)
    out = h3(port, certificate, '/upload', '-X', 'POST', '--data-binary', '@' + str(work / 'mid.bin'))
    assert out == b'%d %d' % (len(blob), sum(blob)), out
    large = bytes((i * 13) % 256 for i in range(5 * 1024 * 1024 + 3))
    (work / 'large.bin').write_bytes(large)
    out = h3(port, certificate, '/large', '-X', 'POST', '--data-binary', '@' + str(work / 'large.bin'))
    assert out == b'%d %d' % (len(large), sum(large)), out
    out = h3(port, certificate, '/large?limit=1000000', '-X', 'POST', '--data-binary', '@' + str(work / 'large.bin'),
             '-w', ' %{http_code}')
    assert out.startswith(b'stopped after ') and out.endswith(b' 413'), out
    out = h3(port, certificate, '/report', '-H', 'Accept-Encoding: gzip')
    assert gzip.decompress(out).startswith(b'[{"id":0'), out[:40]
    big = bytes(ord('a') + i % 26 for i in range(300 * 1024))
    assert h3(port, certificate, '/big') == big
    # Many streams on one connection, each answered in full.
    urls = []
    for i in range(40):
        urls += ['-o', '/dev/null', f'https://127.0.0.1:{port}/big?n={i}']
    command = [curl, '-s', '--http3-only', '--cacert', str(certificate), '-Z', '--parallel-max', '40',
               '-w', '%{http_code} %{size_download}\n', *urls]
    lines = subprocess.run(command, capture_output=True, check=True, timeout=120).stdout.decode().split()
    assert lines == ['200', str(len(big))] * 40, lines[:6]
    # run jobs answer on their own streams.
    hashes = []
    for i in range(6):
        hashes += ['-X', 'POST', '--data-binary', f'p{i}', f'https://127.0.0.1:{port}/hash']
    command = [curl, '-s', '--http3-only', '--cacert', str(certificate), '-Z', *hashes]
    out = subprocess.run(command, capture_output=True, check=True, timeout=60).stdout
    assert len(out) == 6 * 65, out
    # SSE: an open stream receives what /broadcast publishes.
    stream_file = work / 'events.txt'
    with open(stream_file, 'wb') as sink:
        events = subprocess.Popen([curl, '-s', '-N', '--http3-only', '--cacert', str(certificate),
                                   f'https://127.0.0.1:{port}/events'], stdout=sink)
        try:
            deadline = time.time() + 10
            while b'connected' not in stream_file.read_bytes() and time.time() < deadline:
                time.sleep(0.05)
            assert h3(port, certificate, '/broadcast', '-X', 'POST', '--data-binary', 'over h3') == b'sent\n'
            while b'data: over h3' not in stream_file.read_bytes() and time.time() < deadline:
                time.sleep(0.05)
            assert b'data: over h3' in stream_file.read_bytes(), stream_file.read_bytes()
        finally:
            events.terminate()
            events.wait()
    # Closed connections give their slots back (8 per worker here).
    for _ in range(30):
        assert h3(port, certificate, '/health') == b'ok\n'


with tempfile.TemporaryDirectory(prefix='dyn-h3-') as temporary:
    work = Path(temporary)
    certificate, key = work / 'cert.pem', work / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes',
                    '-days', '2', '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1',
                    '-keyout', str(key), '-out', str(certificate)], check=True, capture_output=True, timeout=60)
    binary = work / 'push'
    for mode in ('--debug', '--release'):
        subprocess.run([DYN, 'build', str(ROOT / 'tests/http-evented-push'), mode, '--quiet', '--no-cache',
                        '--output', str(binary)], check=True, timeout=180)
        server = subprocess.Popen([str(binary), 'h3', str(certificate), str(key)], stdout=subprocess.PIPE, text=True)
        try:
            line = server.stdout.readline()
            assert line.startswith('port '), line
            port = int(line.split()[1])
            exercise(port, certificate, work)
            client = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            client.request('POST', '/quit')
            client.getresponse().read()
            assert server.wait(timeout=20) == 0
        finally:
            if server.poll() is None:
                server.kill()
                server.wait()
print('PASS HTTP/3: requests, HEAD, uploads, large bodies, gzip, 40 streams, run jobs, SSE, Alt-Svc, slots freed '
      '(debug/release)')
