#!/usr/bin/env python3
"""Clocks and deadlines: real host, a refused clock (Linux seccomp EPERM), and\nnative substitution.

Substitution copies time.dyn into a temporary fixture; production platform files
are never edited. Every fixture runs in debug and release without libc additions.
"""
import os
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
ENV = dict(os.environ, DYN_SDK=str(ROOT))
REQUIRE = 'fn require(ok: bool) { if !ok { #panic("time result contract") } }\n'
REAL = '''use time "std/time"
''' + REQUIRE + '''fn main() {
  start := time.monotonic_now()
  wall := time.realtime_now()
  require(wall.seconds > 1700000000)
  time.sleep(0)
  time.sleep(-1)
  time.sleep(time.Millisecond)
  end := time.monotonic_now()
  passed := time.elapsed(start, end)
  require(passed >= time.Millisecond)
  deadline := time.deadline_after(time.Second)
  remaining := time.deadline_remaining(&deadline)
  require(remaining > 0 && remaining <= time.Second)
  require(!time.deadline_expired(&deadline))
  zero := time.Deadline{}
  require(time.deadline_expired(&zero) && time.deadline_remaining(&zero) == 0)
}
'''
# A clock the kernel refuses reads zero: nothing fails, deadlines expire.
DENIED = '''use time "std/time"
''' + REQUIRE + '''struct Filter { code: u16, jt: u8, jf: u8, k: u32 }
struct Program { length: u16, filter: *Filter }
fn main() {
  // Deny only clock_gettime with EPERM; allow compiler/runtime exit and I/O.
  filters: [4]Filter = [
    Filter{code: 32, k: 0},
    Filter{code: 21, jf: 1, k: 228},
    Filter{code: 6, k: 327681},
    Filter{code: 6, k: 2147418112},
  ]
  program := Program{length: 4, filter: &filters[0]}
  require(#syscall(157, 38, 1, 0, 0, 0) == 0)
  require(#syscall(317, 1, 0, &program) == 0)
  mono := time.monotonic_now()
  wall := time.realtime_now()
  require(mono.seconds == 0 && mono.nanoseconds == 0 && wall.seconds == 0)
  zero := time.Deadline{}
  require(time.deadline_expired(&zero) && time.deadline_remaining(&zero) == 0)
  time.sleep(0)
}
'''
MOCK = REQUIRE + '''
mock: Instant
sleep_calls: i64 = 0
fn native_clock(monotonic: bool) Instant { return mock }
fn native_sleep(duration: i64) { sleep_calls += 1 }
fn main() {
  sleep(0)
  sleep(-1)
  require(sleep_calls == 0)
  sleep(1)
  require(sleep_calls == 1)
  max: i64 = 9223372036854775807
  min: i64 = -9223372036854775807 - 1
  // An overflowing result fails; the fallback 7 is never a real result here.
  require((checked_add(max, 1) catch 7) == 7)
  require((checked_sub(min, 1) catch 7) == 7)
  require((checked_sub(-1, min) catch 7) == max)
  require((checked_sub(0, min) catch 7) == 7)
  // Spans past the i64 range give its nearest end.
  require(elapsed(Instant{seconds: min}, Instant{seconds: max}) == max)
  require(elapsed(Instant{seconds: max}, Instant{seconds: min}) == min)
  zero := Deadline{}
  require(deadline_expired(&zero) && deadline_remaining(&zero) == 0)
  past := deadline_after(-1)
  require(past.at.seconds == -1 && past.at.nanoseconds == Second - 1)
  require(deadline_expired(&past) && deadline_remaining(&past) == 0)
  future := deadline_after(Second + 1)
  require(future.at.seconds == 1 && future.at.nanoseconds == 1)
  require(!deadline_expired(&future) && deadline_remaining(&future) == Second + 1)
  far := Deadline{at: Instant{seconds: max}}
  require(deadline_remaining(&far) == max)
  mock = Instant{seconds: max, nanoseconds: Second - 1}
  after := deadline_after(Second)
  require(after.at.seconds == max)
  mock = Instant{seconds: 4, nanoseconds: Second - 1}
  after = deadline_after(1)
  require(after.at.seconds == 5 && after.at.nanoseconds == 0)
  mock = Instant{seconds: 4}
  after = deadline_after(-1)
  require(after.at.seconds == 3 && after.at.nanoseconds == Second - 1)
}
'''


def run(root, name, source):
    work = root / name
    work.mkdir()
    (work / 'main.dyn').write_text(source)
    for mode in ('debug', 'release'):
        output = work / ('test-' + mode)
        subprocess.run([DYN, 'build', str(work), '--no-cache', '--quiet',
                        '--' + mode, '--output', str(output)],
                       env=ENV, check=True, timeout=120)
        subprocess.run([str(output)], env=ENV, check=True, timeout=10)
        print('PASS time ' + name + ' ' + mode, flush=True)


def main():
    with tempfile.TemporaryDirectory(prefix='dyn-time-results-') as tmp:
        root = Path(tmp)
        run(root, 'actual-clock', REAL)
        run(root, 'substituted-native', (ROOT / 'std/time/time.dyn').read_text() + '\n' + MOCK)
        if platform.system() == 'Linux' and platform.machine() == 'x86_64':
            run(root, 'seccomp-clock-eperm', DENIED)
        else:
            print('SKIP time seccomp-clock-eperm: Linux x86_64 required')


if __name__ == '__main__':
    main()
