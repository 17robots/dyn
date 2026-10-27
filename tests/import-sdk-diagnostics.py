#!/usr/bin/env python3
"""Real resolver distinguishes missing SDK modules from project paths."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve()
with tempfile.TemporaryDirectory(prefix='dyn-sdk-diagnostic-') as temporary:
    work = Path(temporary)
    installed = work/'bin'/DYN.name
    installed.parent.mkdir()
    shutil.copy2(DYN, installed)
    project = work/'project'
    project.mkdir()
    sdk = work/'sdk'
    sdk.mkdir()
    env = dict(os.environ, DYN_SDK=str(sdk), DYN_CACHE_DIR=str(work/'cache'))
    source = project/'main.dyn'
    def check(path, sdk_import):
        source.write_text(f'use "{path}" missing\nfn main() {{}}\n')
        result = subprocess.run([str(installed), 'check', str(project), '--quiet'], env=env,
                                text=True, capture_output=True, timeout=30)
        assert result.returncode == 1, result.stderr
        assert path in result.stderr, result.stderr
        if sdk_import:
            assert 'not found in the selected Dyn SDK' in result.stderr, result.stderr
            assert 'DYN_SDK' in result.stderr and 'std/ and vendor/' in result.stderr, result.stderr
            assert 'inside project root' not in result.stderr, result.stderr
        else:
            assert 'does not resolve inside project root' in result.stderr, result.stderr
            assert 'selected Dyn SDK' not in result.stderr, result.stderr
    check('std/ui/box', True)
    check('vendor/window/native', True)
    check('./missing', False)
    check('missing', False)
    # DYN_SDK guidance names the directory the resolver actually accepts.
    for path in ('std/example', 'vendor/example'):
        module = sdk/path
        module.mkdir(parents=True)
        (module/'example.dyn').write_text('pub fn value() i32 { return 7 }\n')
        source.write_text(f'use "{path}" example\nfn main() {{ if example.value()!=7 {{ #panic("SDK") }} }}\n')
        result = subprocess.run([str(installed), 'check', str(project), '--quiet'], env=env,
                                text=True, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr
print('PASS SDK import diagnostics and configured SDK resolution')
