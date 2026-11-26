#!/usr/bin/env python3
"""Recording a failure costs a call to fail.make and a 40-byte copy, not a
copy of a large failure at every site. fail.set copies the failure field by
field, so where it is inlined the copy needs no overlap check. Each extra
site that builds a fail.Failure stays under 220 bytes of code (it was 386),
and the program still reports the right failure."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())


def program(sites):
    functions = ''.join(f'''fn check{i}(status: *fail.Status, value: u64) {{
  if value == {i + 1000} {{
    fail.set(status, fail.make(fail.Kind.InvalidInput, "check {i}", "", "value out of range"))
  }}
}}
''' for i in range(sites))
    calls = ''.join(f'  check{i}(&status, value)\n' for i in range(sites))
    return f'''use "std/fail"
use "std/io"
use "std/process"
use "std/mem"

{functions}
fn main() {{
  arena := mem.arena_alloc(4096)
  defer mem.arena_release(arena)
  status: fail.Status
  arguments := process.arguments(arena, &status)
  value := #cast(u64, arguments.len) + 999
{calls}  storage: [256]u8
  if status.failed {{
    io.println("{{}}", fail.describe(storage[..], status.failure))
  }}
}}
'''


def text_size(path):
    data = subprocess.run(['size', str(path)], capture_output=True, text=True, check=True).stdout
    return int(data.splitlines()[-1].split()[0])


with tempfile.TemporaryDirectory(prefix='dyn-failure-site-size-') as temporary:
    sizes = {}
    for sites in (2, 22):
        project = Path(temporary) / f'sites{sites}'
        project.mkdir()
        (project / 'main.dyn').write_text(program(sites))
        output = project / 'program'
        subprocess.run([DYN, 'build', str(project), '--release', '--quiet', '--no-cache', '--output', str(output)],
                       check=True, timeout=120)
        sizes[sites] = text_size(output)
        # One argument (the program) makes value 1000: check0 fails.
        run = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
        assert run.returncode == 0 and run.stdout == 'check 0: value out of range\n', run
    per_site = (sizes[22] - sizes[2]) / 20
    assert per_site < 220, (sizes, per_site)
print(f'PASS failure sites: {per_site:.0f} bytes of code each; the failure is reported')
