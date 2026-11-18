#!/usr/bin/env python3
"""A for loop with no condition and no break leaves only through return or a
panic, so a function that ends with one needs no return after it. Code after
it is still allowed, and a loop with a break still needs one."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
GOOD = '''use "std/io"

fn first_even(values: []const i32) i32 {
  index: usize = 0
  for {
    if values[index] % 2 == 0 { return values[index] }
    index += 1
  }
}

fn nested(limit: i32) i32 {
  count: i32 = 0
  for {
    for i in 0..3 {
      if i == 2 { break }
      count += 1
    }
    if count >= limit { return count }
  }
}

fn branches(flag: bool) i32 {
  if flag {
    return 1
  } else {
    for {
      return 2
    }
  }
}

fn defensive(limit: i32) i32 {
  total: i32 = 0
  for {
    total += 1
    if total == limit { return total }
  }
  return -1
}

fn main() {
  values: [3]i32 = [1, 3, 4]
  io.println("{} {} {} {} {}", first_even(values[..]), nested(5), branches(true), branches(false), defensive(4))
}
'''
BROKEN = '''fn stops(limit: i32) i32 {
  total: i32 = 0
  for {
    total += 1
    if total == limit { break }
  }
}

fn main() {
  _ = stops(3)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-endless-loop-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(GOOD)
    # The tree backend (DYN_NO_SSA) too: the code after the loop is unreachable.
    for flags, tree in (([], False), (['--release'], False), (['--release'], True)):
        output = project / 'program'
        environment = dict(os.environ, DYN_NO_SSA='1') if tree else None
        subprocess.run([DYN, 'build', str(project), '--quiet', '--no-cache', '--output', str(output), *flags],
                       check=True, timeout=120, env=environment)
        result = subprocess.run([str(output)], capture_output=True, text=True, timeout=10, check=True)
        assert result.stdout == '4 6 1 2 4\n', result.stdout
    (project / 'main.dyn').write_text(BROKEN)
    checked = subprocess.run([DYN, 'check', str(project)], capture_output=True, text=True, timeout=60)
    assert checked.returncode != 0 and 'non-void function may exit without return' in checked.stderr, checked.stderr
print('PASS endless loops: no return needed after for {} without break; code after it allowed; break still needs one; tree backend too')
