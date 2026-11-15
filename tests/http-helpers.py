#!/usr/bin/env python3
"""Pure std/net/http helpers (dates, status reasons, cookies, SSE, MIME types,
Accept-Encoding, If-None-Match, multipart) and the std/encoding/json Writer."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())

EXPECTED = '''Sun, 06 Nov 1994 08:49:37 GMT
Tue, 29 Feb 2000 00:00:00 GMT
951782400
Syntax
Not Modified
Status
sid=abc; Path=/; Max-Age=60; Secure; HttpOnly; SameSite=Strict
sid=; Max-Age=0
Syntax
Syntax
dark s3 false
event: update
id: 42
data: one
data: two
data: three

Syntax
text/javascript; charset=utf-8 application/octet-stream image/svg+xml
false true true
true true false
part title   2
part f a.txt text/plain 4
parts end Ok
'''

with tempfile.TemporaryDirectory(prefix='dyn-http-helpers-') as temporary:
    for mode in ('--debug', '--release'):
        program = Path(temporary) / 'helpers'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/http-helpers'), mode, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=180)
        output = subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=30).stdout
        assert output.startswith(EXPECTED), output
        rest = output[len(EXPECTED):].rstrip('\n').split('\n')
        assert json.loads(rest[0]) == {'a': [-1, 18446744073709551615, 0.1, False, None, 'q"\\\n ', {'x': 1}], 'b': {}}, rest[0]
        assert rest[1:] == ['false 0', 'true', 'limit 3 false true true', '2001:db8::1:0:1', 'true'], rest
print('http helpers ok')
