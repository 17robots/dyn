#!/usr/bin/env python3
"""Run the compiler itself on its host, including cache, diagnostics and LSP."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = ROOT/'build'/('dyn-release.exe' if os.name == 'nt' else 'dyn-release')
report = dict(host=platform.platform(), compiler_sha256=hashlib.sha256(DYN.read_bytes()).hexdigest(), status='running', checks=[])

def run(*args, success=True, **kwargs):
    binary = isinstance(kwargs.get('input'), bytes)
    result = subprocess.run([str(a) for a in args], capture_output=True, text=not binary, timeout=120, **kwargs)
    if binary:
        result.stdout = result.stdout.decode('utf-8')
        result.stderr = result.stderr.decode('utf-8')
    if (result.returncode == 0) != success:
        raise RuntimeError(f'{args}: exit {result.returncode}\n{result.stdout}\n{result.stderr}')
    return result

try:
    with tempfile.TemporaryDirectory(prefix='dyn host with spaces ') as temporary:
        work = Path(temporary)
        env = dict(os.environ, DYN_CACHE_DIR=str(work/'cache'))
        env.pop('DYN_SDK', None)
        # No target override: the native compiler must select its own host.
        run(DYN, 'version')
        project = work/'project with spaces'
        shutil.copytree(ROOT/'tests/smoke', project)
        run(DYN, 'check', project, env=env)
        report['checks'].append('version and check')
        output = work/('program.exe' if os.name == 'nt' else 'program')
        for options in ([], ['--release']):
            for _ in range(2):
                run(DYN, 'build', project, '--output', output, *options, env=env)
                run(output)
            run(DYN, 'run', project, *options, env=env)
        report['checks'].append('debug/release build, cache reuse, output replacement and run')
        editable = work/'editable'; editable.mkdir()
        source = editable/'main.dyn'
        source.write_text('fn main() { if 1 == 2 { #panic("cache") } }\n')
        run(DYN, 'build', editable, '--release', '--output', output, env=env)
        run(output)
        timestamp = source.stat()
        source.write_text(source.read_text().replace('1 == 2', '1 == 1'))
        os.utime(source, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
        run(DYN, 'build', editable, '--release', '--output', output, env=env)
        run(output, success=False)
        report['checks'].append('same-size source change with restored mtime invalidates cache')
        (project/'main.dyn').write_text('fn main() { missing_symbol() }\n')
        result = run(DYN, 'check', project, success=False, env=env)
        assert result.returncode == 1 and result.stderr.strip(), result.stderr
        report['checks'].append('invalid source rejected')
        messages = [dict(jsonrpc='2.0',id=1,method='initialize',params={}),
                    dict(jsonrpc='2.0',id=2,method='shutdown',params=None),
                    dict(jsonrpc='2.0',method='exit',params=None)]
        wire = ''.join(f'Content-Length: {len(body.encode())}\r\n\r\n{body}' for body in map(json.dumps,messages))
        # Send protocol bytes: Windows text pipes otherwise translate LF to CRLF.
        result = run(DYN, 'lsp', input=wire.encode('utf-8'), env=env)
        assert 'capabilities' in result.stdout and '"id":2' in result.stdout.replace(' ', '')
        report['checks'].append('LSP initialize/shutdown over pipes')
    report['status'] = 'passed'
except BaseException as error:
    report.update(status='failed',error=str(error)); raise
finally:
    (ROOT/'build/compiler-host.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS native compiler host:',platform.system(),'; '.join(report['checks']))
