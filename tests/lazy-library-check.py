#!/usr/bin/env python3
"""dyn check and dyn vet check library function bodies only when the program
can reach them: an error in an unused std function does not reach the user,
an error in a used one does, the program's own code is always checked, and
checking the library module itself checks all of it."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
PROBE = '''pub fn used() i32 {
  return helper()
}
fn helper() i32 {
  return 1
}
pub fn unused() i32 {
  value: i32 = "not a number"
  return value
}
'''
def check(sdk, project, command='check'):
    env = dict(os.environ, DYN_SDK=str(sdk))
    return subprocess.run([DYN, command, str(project), '--no-cache'], capture_output=True, text=True, timeout=120, env=env)

with tempfile.TemporaryDirectory(prefix='dyn-lazy-library-') as temporary:
    work = Path(temporary)
    sdk = work / 'sdk'
    sdk.mkdir()
    for entry in ROOT.iterdir():
        if entry.name not in ('std', 'build', 'tests', 'examples', '.jj'):
            (sdk / entry.name).symlink_to(entry)
    (sdk / 'std').mkdir()
    for module in (ROOT / 'std').iterdir():
        (sdk / 'std' / module.name).symlink_to(module)
    (sdk / 'std' / 'probe').mkdir()
    (sdk / 'std' / 'probe' / 'probe.dyn').write_text(PROBE)

    def program(name, body):
        project = work / name
        project.mkdir()
        (project / 'main.dyn').write_text('use "std/probe"\n\nfn main() {\n' + body + '}\n')
        return project

    uses_used = program('uses-used', '  _ = probe.used()\n')
    for command in ('check', 'vet'):
        result = check(sdk, uses_used, command)
        assert result.returncode == 0, (command, result.stdout + result.stderr)
    uses_unused = program('uses-unused', '  _ = probe.unused()\n')
    result = check(sdk, uses_unused)
    assert result.returncode != 0 and 'probe.dyn' in result.stderr, result.stderr
    own_error = program('own-error', '  _ = probe.used()\n  x: i32 = "text"\n  _ = x\n')
    result = check(sdk, own_error)
    assert result.returncode != 0 and 'main.dyn' in result.stderr and 'probe.dyn' not in result.stderr, result.stderr
    result = check(sdk, sdk / 'std' / 'probe')
    assert result.returncode != 0 and 'probe.dyn' in result.stderr, result.stderr
print('PASS lazy library check: unused library bodies are skipped, used ones and the program are checked')
