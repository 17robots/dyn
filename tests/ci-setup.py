#!/usr/bin/env python3
"""Exercise actual CI apt rewrites for direct and indirect runner sources."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap

ROOT = Path(__file__).resolve().parents[1]
if sys.platform != 'linux' or not shutil.which('bash') or not shutil.which('sed'):
    print('SKIP CI apt setup: Linux bash/sed required')
    raise SystemExit(0)
action = (ROOT/'.github/actions/setup-compiler/action.yml').read_text()
script = textwrap.dedent(action.split('      run: |\n', 1)[1])
subprocess.run(['bash', '-n'], input=script, text=True, check=True, timeout=10)
prefix = script.split('apt_options=', 1)[0]
for indirect in (False, True):
    with tempfile.TemporaryDirectory(prefix='dyn-ci-apt-') as temporary:
        work = Path(temporary)
        sources, mirrors = work/'ubuntu.sources', work/'apt-mirrors.txt'
        uri = ('mirror+file:/etc/apt/apt-mirrors.txt' if indirect
               else 'http://azure.archive.ubuntu.com/ubuntu')
        sources.write_text('Types: deb\nURIs: '+uri+'\nSuites: noble noble-updates\n'
                           'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n\n'
                           'Types: deb\nURIs: http://security.ubuntu.com/ubuntu\n'
                           'Suites: noble-security\n'
                           'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n')
        if indirect:
            mirrors.write_text('http://azure.archive.ubuntu.com/ubuntu/\tpriority:1\n'
                               'http://archive.ubuntu.com/ubuntu/\tpriority:2\n')
        staged = prefix.replace('/etc/apt/sources.list.d/ubuntu.sources', str(sources))
        staged = staged.replace('/etc/apt/apt-mirrors.txt', str(mirrors)).replace('sudo sed ', 'sed ')
        for _ in range(2):
            subprocess.run(['bash', '-c', staged], check=True, timeout=10)
        result = sources.read_text()
        assert result.count('Types: deb deb-src') == 2
        assert result.count('Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg') == 2
        assert 'URIs: http://security.ubuntu.com/ubuntu' in result
        assert 'Suites: noble noble-updates' in result and 'Suites: noble-security' in result
        archive = mirrors.read_text() if indirect else result
        assert 'azure.archive.ubuntu.com' not in archive
        assert 'https://archive.ubuntu.com/ubuntu' in archive
        if indirect:
            assert 'mirror+file:/etc/apt/apt-mirrors.txt' in result
            assert 'priority:1' in archive and 'priority:2' in archive
        print('PASS CI apt setup:', 'indirect' if indirect else 'direct', '(idempotent)')
