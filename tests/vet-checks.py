#!/usr/bin/env python3
"""dyn vet reports unused locals and imports and casts a slot makes implicit;
--unsafe lists unsafe operations."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
module = str(ROOT / 'tests/vet-checks')
plain = subprocess.run([DYN, 'vet', module], capture_output=True, text=True, timeout=60)
assert plain.returncode == 1 and 'local is never used' in plain.stderr and 'unsafe:' not in plain.stderr, plain
full = subprocess.run([DYN, 'vet', '--unsafe', module], capture_output=True, text=True, timeout=60)
for message in ('unsafe: #slice', 'unsafe: #offset', 'unsafe: pointer cast', 'unsafe: size multiplication'):
    assert message in full.stderr, (message, full.stderr)
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root/'main.dyn').write_text('use "std/mem"\nuse "std/fmt" f\nfn main() {\n  helper()\n}\n')
    (root/'other.dyn').write_text('fn helper() {\n  arena := mem.arena_create(4096)\n  mem.arena_release(arena)\n}\n')
    imports = subprocess.run([DYN, 'vet', str(root)], capture_output=True, text=True, timeout=60)
    assert imports.returncode == 1 and imports.stderr.count('import is never used') == 1, imports
    assert 'main.dyn:2:' in imports.stderr, imports
    (root/'other.dyn').unlink()
    (root/'main.dyn').write_text("""struct P { n: u64 }
fn take(n: u64) u64 {
  return #cast(u64, n)
}
fn keep(n: u32) u64 {
  wide := #cast(u64, n)
  return wide * #cast(u64, n)
}
fn main() {
  a: u32 = 3
  b: u64 = #cast(u64, a)
  d: [4]u8 = []
  e := d[#cast(usize, a)]
  p := P{ n: #cast(u64, a) }
  _ = take(#cast(u64, e)) + keep(a) + b + p.n
}
""")
    casts = subprocess.run([DYN, 'vet', str(root)], capture_output=True, text=True, timeout=60)
    found = sorted(int(line.split(':')[1]) for line in casts.stderr.splitlines() if 'cast is implicit here' in line)
    # Untyped locals and binary operands keep their casts: those set the type.
    assert found == [3, 11, 13, 14, 15], casts.stderr
print('PASS vet: unused locals, implicit casts and the unsafe report')
