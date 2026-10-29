#!/usr/bin/env python3
"""Module-wide imports deduplicate across files and diagnose conflicts locally."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-file-imports-') as tmp:
    project = Path(tmp)
    for name, value in [('left', 11), ('right', 22)]:
        (project / name).mkdir()
        (project / name / 'lib.dyn').write_text(f'pub fn value() i32 {{ return {value} }}\n')
    main = project / 'main.dyn'
    other = project / 'other.dyn'

    def run(command, success=True):
        result = subprocess.run([DYN, command, str(project), '--no-cache'],
                                capture_output=True, text=True, timeout=60)
        assert (result.returncode == 0) == success, result.stderr
        return result.stderr

    main.write_text('use "left" lib\nfn main() { if lib.value() != 11 || other() != 11 { #panic("imports") } }\n')
    other.write_text('fn other() i32 { return lib.value() }\n')
    run('check')
    run('vet')
    def build_and_run():
        for flags in [[], ['--release']]:
            output = project / 'program'
            result = subprocess.run([DYN, 'build', str(project), '--no-cache', '--output', str(output), *flags],
                                    capture_output=True, text=True, timeout=120)
            assert result.returncode == 0, result.stderr
            subprocess.run([str(output)], check=True, timeout=10)

    build_and_run()
    other.write_text('use "left" lib\nfn other() i32 { return lib.value() }\n')
    run('check')
    run('vet')
    build_and_run()
    other.write_text('use "left" different\nfn other() i32 { return different.value() }\n')
    run('check')
    run('vet')
    build_and_run()
    other.write_text('use "./left" lib\nfn other() i32 { return lib.value() }\n')
    run('check')
    run('vet')
    build_and_run()
    other.write_text('fn other() i32 { return lib.value() }\n')
    run('check')
    run('vet')
    other.write_text('use "right" lib\nfn other() i32 { return 0 }\n')
    assert "duplicate import alias 'lib'" in run('check', False)
    other.write_text('use "left" lib\nuse "left" lib\nfn other() i32 { return 0 }\n')
    assert "duplicate import alias 'lib'" in run('check', False)
    other.write_text('use "left" a\nuse "left" b\nfn other() i32 { return a.value() + b.value() }\n')
    run('check')
    assert 'imported more than once' in run('vet', False)
print('PASS module-wide imports, deduplication, native execution and duplicate diagnostics')
