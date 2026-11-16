#!/usr/bin/env python3
"""json.object_of/array_of, html.print, std/net/http/session, http.assets_of,
process.environment_or and log lines, in debug and release."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
EXPECTED = '''[{"id":1,"author":"ann","body":"hi \\"there\\"","created":99,"ok":true,"score":1.5,"small":7,"count":3},{"id":-2,"author":"bo","body":"x\\n","created":0,"ok":false,"score":-0.25,"small":0,"count":0}]
{"id":-2,"author":"bo","body":"x\\n","created":0,"ok":false,"score":-0.25,"small":0,"count":0}
nested fails true
<p id="42" class="x&quot;y">&lt;b&gt; true <i>a&amp;b</i></p><style>p { color: red }</style>-7 [<br>] {?}
start true 64 32 sid=
cold false
remembered true hit true user 7 data ann csrf true false
expired false
forget sid=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax
after forget false
assets 2 text/javascript; charset=utf-8 text/css; charset=utf-8
env yes fallback
info: hello a=1 b=two
'''
with tempfile.TemporaryDirectory(prefix='dyn-web-batteries-') as temporary:
    program = Path(temporary) / 'program'
    for mode in ('--debug', '--release'):
        subprocess.run([DYN, 'build', str(ROOT / 'tests/web-batteries'), mode, '--quiet', '--no-cache', '--output', str(program)],
                       check=True, timeout=180)
        output = subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=30,
                                env={**os.environ, 'WEB_BATTERIES_SET': 'yes'}).stdout
        assert output == EXPECTED, (mode, output)
print('PASS web batteries: object_of/array_of, html.print, sessions, assets_of, environment_or, log lines (debug/release)')
