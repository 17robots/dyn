#!/usr/bin/env python3
"""HTTP throughput and latency floor: the evented test server and the
thread-per-connection flagship server under tools/httpbench. The floors sit far below a normal machine's numbers, so only
regressions of the "40 ms per response" kind fail: those cut throughput by
three orders of magnitude. Prints the measured numbers for the log."""
import http.client
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
MIN_RATE = int(os.environ.get('DYN_HTTP_MIN_RATE', '20000'))
MAX_P99_US = int(os.environ.get('DYN_HTTP_MAX_P99_US', '20000'))
if sys.platform != 'linux':
    print('SKIP HTTP benchmark floor requires Linux')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-http-bench-') as temporary:
    server_program = Path(temporary) / 'server'
    bench_program = Path(temporary) / 'httpbench'
    flagship_program = Path(temporary) / 'flagship'
    for source, output in ((ROOT / 'tests/http-evented', server_program), (ROOT / 'tools/httpbench', bench_program),
                           (ROOT / 'tests/flagship-http', flagship_program)):
        subprocess.run([DYN, 'build', str(source), '--release', '--no-cache', '--quiet', '--output', str(output)],
                       check=True, timeout=300)
    def measure(port, path, connections):
        line = subprocess.run([str(bench_program), str(port), path, str(connections), '2'],
                              capture_output=True, text=True, check=True, timeout=60).stdout.split()
        values = dict(zip(line[::2], map(int, line[1::2])))
        print(f'{label} {path} c={connections}: {values["rate"]} req/s, p50 {values["p50_us"]} us, '
              f'p99 {values["p99_us"]} us, errors {values["errors"]}')
        assert values['errors'] == 0, values
        assert values['rate'] >= MIN_RATE, (label, path, connections, values)
        assert values['p99_us'] <= MAX_P99_US, (label, path, connections, values)

    def quit(port):
        client = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        client.request('POST', '/quit')
        client.getresponse().read()
        client.close()

    # The evented test server allows 2 workers x 16 connections; the flagship
    # server has 4 threads, one connection each.
    for label, program, arguments, runs in (
            ('evented', server_program, ['single'], (('/health', 1), ('/health', 8), ('/stream', 8))),
            ('threads', flagship_program, [], (('/health', 1), ('/health', 4)))):
        server = subprocess.Popen([str(program)] + arguments, stdout=subprocess.PIPE)
        try:
            port = int(server.stdout.readline().decode().split()[1])
            for path, connections in runs:
                measure(port, path, connections)
            quit(port)
            assert server.wait(timeout=15) == 0
        finally:
            if server.poll() is None:
                server.kill()
                server.wait()
print(f'PASS HTTP benchmark floor: >= {MIN_RATE} req/s and p99 <= {MAX_P99_US} us')
