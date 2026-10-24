#!/usr/bin/env python3
"""Clock/deadline results: real host, Linux seccomp EPERM, native substitution.

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
REAL = '''use "std/time" time
use "std/errors" errors
''' + REQUIRE + '''fn main() {
  start := time.monotonic_now()
  wall := time.realtime_now()
  require(start.ok && start.kind == errors.Kind.None && start.error == 0)
  require(wall.ok && wall.kind == errors.Kind.None && wall.error == 0)
  zero_sleep := time.sleep(0)
  require(zero_sleep.ok && zero_sleep.kind == errors.Kind.None && zero_sleep.error == 0)
  require(time.sleep(-1).ok)
  slept := time.sleep(time.Millisecond)
  require(slept.ok && slept.kind == errors.Kind.None && slept.error == 0)
  end := time.monotonic_now()
  require(end.ok)
  passed := time.elapsed(start.value, end.value)
  require(passed.ok && passed.value >= time.Millisecond && passed.kind == errors.Kind.None && passed.error == 0)
  deadline := time.deadline_after(time.Second)
  require(deadline.ok && deadline.kind == errors.Kind.None && deadline.error == 0)
  remaining := time.deadline_remaining(&deadline.value)
  require(remaining.ok && remaining.value > 0 && remaining.value <= time.Second && remaining.kind == errors.Kind.None && remaining.error == 0)
  expired := time.deadline_expired(&deadline.value)
  require(expired.ok && !expired.value && expired.kind == errors.Kind.None && expired.error == 0)
  zero := time.Deadline{}
  expired = time.deadline_expired(&zero)
  require(expired.ok && expired.value)
  remaining = time.deadline_remaining(&zero)
  require(remaining.ok && remaining.value == 0)
  expired = time.deadline_expired(nil)
  require(!expired.ok && expired.kind == errors.Kind.InvalidInput && expired.error == 0)
  remaining = time.deadline_remaining(nil)
  require(!remaining.ok && remaining.kind == errors.Kind.InvalidInput && remaining.error == 0)
}
'''
DENIED = '''use "std/time" time
use "std/errors" errors
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
  require(!mono.ok && mono.error == -1 && mono.kind == errors.Kind.PermissionDenied)
  require(!wall.ok && wall.error == -1 && wall.kind == errors.Kind.PermissionDenied)
  after := time.deadline_after(0)
  require(!after.ok && after.error == -1 && after.kind == errors.Kind.PermissionDenied)
  zero := time.Deadline{}
  expired := time.deadline_expired(&zero)
  require(!expired.ok && expired.error == -1 && expired.kind == errors.Kind.PermissionDenied)
  remaining := time.deadline_remaining(&zero)
  require(!remaining.ok && remaining.error == -1 && remaining.kind == errors.Kind.PermissionDenied)
  require(time.sleep(0).ok)
}
'''
MOCK = REQUIRE + '''mock: ClockResult
sleep_mock: SleepResult
sleep_calls: i64 = 0
fn native_clock(monotonic: bool) ClockResult { return mock }
fn native_sleep(duration: i64) SleepResult { sleep_calls += 1
return sleep_mock }
fn main() {
  zero_clock := ClockResult{}
  zero_sleep := SleepResult{}
  zero_deadline := DeadlineResult{}
  zero_expired := ExpiredResult{}
  zero_duration := DurationResult{}
  require(!zero_clock.ok && zero_clock.kind == errors.Kind.None && zero_clock.error == 0)
  require(!zero_sleep.ok && zero_sleep.kind == errors.Kind.None && zero_sleep.error == 0)
  require(!zero_deadline.ok && zero_deadline.kind == errors.Kind.None && zero_deadline.error == 0)
  require(!zero_expired.ok && zero_expired.kind == errors.Kind.None && zero_expired.error == 0)
  require(!zero_duration.ok && zero_duration.kind == errors.Kind.None && zero_duration.error == 0)
  zero := Deadline{}
  for native in [0, -73] {
    mock = ClockResult{ kind: errors.Kind.PermissionDenied, error: #cast(isize, native) }
    mono := monotonic_now()
    wall := realtime_now()
    require(!mono.ok && mono.kind == mock.kind && mono.error == mock.error)
    require(!wall.ok && wall.kind == mock.kind && wall.error == mock.error)
    after := deadline_after(1)
    require(!after.ok && after.kind == mock.kind && after.error == mock.error && after.value.at.seconds == 0 && after.value.at.nanoseconds == 0)
    expired := deadline_expired(&zero)
    require(!expired.ok && !expired.value && expired.kind == mock.kind && expired.error == mock.error)
    remaining := deadline_remaining(&zero)
    require(!remaining.ok && remaining.value == 0 && remaining.kind == mock.kind && remaining.error == mock.error)
    sleep_mock = SleepResult{ kind: errors.Kind.Interrupted, error: #cast(isize, native) }
    slept := sleep(1)
    require(!slept.ok && slept.kind == sleep_mock.kind && slept.error == sleep_mock.error)
  }
  require(sleep_calls == 2)
  require(sleep(0).ok && sleep(-1).ok && sleep_calls == 2)
  sleep_mock = SleepResult{ok: true}
  require(sleep(1).ok && sleep_calls == 3)
  require(deadline_expired(nil).kind == errors.Kind.InvalidInput)
  require(deadline_expired(nil).error == 0)
  require(deadline_remaining(nil).kind == errors.Kind.InvalidInput)
  require(deadline_remaining(nil).error == 0)
  max: i64 = 9223372036854775807
  min: i64 = -9223372036854775807 - 1
  add := checked_add(max, 1)
  sub := checked_sub(min, 1)
  require(!add.ok && add.kind == errors.Kind.None && add.error == 0)
  require(!sub.ok && sub.kind == errors.Kind.None && sub.error == 0)
  require(checked_sub(-1, min).value == max)
  require(!checked_sub(0, min).ok)
  require(!elapsed(Instant{seconds: min}, Instant{seconds: max}).ok)
  mock = ClockResult{ok: true}
  require(deadline_expired(&zero).ok && deadline_expired(&zero).value)
  require(deadline_remaining(&zero).ok && deadline_remaining(&zero).value == 0)
  past := deadline_after(-1)
  require(past.ok && past.value.at.seconds == -1 && past.value.at.nanoseconds == Second - 1)
  require(deadline_expired(&past.value).value && deadline_remaining(&past.value).value == 0)
  future := deadline_after(Second + 1)
  require(future.ok && future.value.at.seconds == 1 && future.value.at.nanoseconds == 1)
  require(!deadline_expired(&future.value).value && deadline_remaining(&future.value).value == Second + 1)
  far := Deadline{at: Instant{seconds: max}}
  overflow := deadline_remaining(&far)
  require(!overflow.ok && overflow.kind == errors.Kind.Overflow && overflow.error == 0)
  mock = ClockResult{value: Instant{seconds: max, nanoseconds: Second - 1}, ok: true}
  after := deadline_after(1)
  require(!after.ok && after.kind == errors.Kind.Overflow && after.error == 0)
  mock = ClockResult{value: Instant{seconds: min}, ok: true}
  after = deadline_after(-1)
  require(!after.ok && after.kind == errors.Kind.Overflow && after.error == 0)
  mock = ClockResult{value: Instant{seconds: 4, nanoseconds: Second - 1}, ok: true}
  after = deadline_after(1)
  require(after.ok && after.value.at.seconds == 5 && after.value.at.nanoseconds == 0)
  mock = ClockResult{value: Instant{seconds: 4}, ok: true}
  after = deadline_after(-1)
  require(after.ok && after.value.at.seconds == 3 && after.value.at.nanoseconds == Second - 1)
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
