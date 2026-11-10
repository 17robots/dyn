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
use "std/io" errors
''' + REQUIRE + '''fn main() {
  start := time.monotonic_now()
  wall := time.realtime_now()
  require(start.failure.kind == errors.Kind.Ok && start.failure.native == 0)
  require(wall.failure.kind == errors.Kind.Ok && wall.failure.native == 0)
  zero_sleep := time.sleep(0)
  require(zero_sleep.failure.kind == errors.Kind.Ok && zero_sleep.failure.native == 0)
  require(time.sleep(-1).failure.kind == errors.Kind.Ok)
  slept := time.sleep(time.Millisecond)
  require(slept.failure.kind == errors.Kind.Ok && slept.failure.native == 0)
  end := time.monotonic_now()
  require(end.failure.kind == errors.Kind.Ok)
  passed := time.elapsed(start.value, end.value)
  require(passed.failure.kind == errors.Kind.Ok && passed.value >= time.Millisecond && passed.failure.kind == errors.Kind.Ok && passed.failure.native == 0)
  deadline := time.deadline_after(time.Second)
  require(deadline.failure.kind == errors.Kind.Ok && deadline.failure.native == 0)
  remaining := time.deadline_remaining(&deadline.value)
  require(remaining.failure.kind == errors.Kind.Ok && remaining.value > 0 && remaining.value <= time.Second && remaining.failure.kind == errors.Kind.Ok && remaining.failure.native == 0)
  expired := time.deadline_expired(&deadline.value)
  require(expired.failure.kind == errors.Kind.Ok && !expired.value && expired.failure.kind == errors.Kind.Ok && expired.failure.native == 0)
  zero := time.Deadline{}
  expired = time.deadline_expired(&zero)
  require(expired.failure.kind == errors.Kind.Ok && expired.value)
  remaining = time.deadline_remaining(&zero)
  require(remaining.failure.kind == errors.Kind.Ok && remaining.value == 0)
  expired = time.deadline_expired(nil)
  require(expired.failure.kind != errors.Kind.Ok && expired.failure.kind == errors.Kind.InvalidInput && expired.failure.native == 0)
  remaining = time.deadline_remaining(nil)
  require(remaining.failure.kind != errors.Kind.Ok && remaining.failure.kind == errors.Kind.InvalidInput && remaining.failure.native == 0)
}
'''
DENIED = '''use "std/time" time
use "std/io" errors
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
  require(mono.failure.kind != errors.Kind.Ok && mono.failure.native == -1 && mono.failure.kind == errors.Kind.PermissionDenied)
  require(wall.failure.kind != errors.Kind.Ok && wall.failure.native == -1 && wall.failure.kind == errors.Kind.PermissionDenied)
  after := time.deadline_after(0)
  require(after.failure.kind != errors.Kind.Ok && after.failure.native == -1 && after.failure.kind == errors.Kind.PermissionDenied)
  zero := time.Deadline{}
  expired := time.deadline_expired(&zero)
  require(expired.failure.kind != errors.Kind.Ok && expired.failure.native == -1 && expired.failure.kind == errors.Kind.PermissionDenied)
  remaining := time.deadline_remaining(&zero)
  require(remaining.failure.kind != errors.Kind.Ok && remaining.failure.native == -1 && remaining.failure.kind == errors.Kind.PermissionDenied)
  require(time.sleep(0).failure.kind == errors.Kind.Ok)
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
  require(zero_clock.failure.kind == io.Kind.Ok && zero_clock.failure.native == 0)
  require(zero_sleep.failure.kind == io.Kind.Ok && zero_sleep.failure.native == 0)
  require(zero_deadline.failure.kind == io.Kind.Ok && zero_deadline.failure.native == 0)
  require(zero_expired.failure.kind == io.Kind.Ok && zero_expired.failure.native == 0)
  require(zero_duration.failure.kind == io.Kind.Ok && zero_duration.failure.native == 0)
  zero := Deadline{}
  for native in [0, -73] {
    mock = ClockResult{ failure: io.Failure{ kind: io.Kind.PermissionDenied, native: #cast(isize, native) } }
    mono := monotonic_now()
    wall := realtime_now()
    require(mono.failure.kind != io.Kind.Ok && mono.failure.kind == mock.failure.kind && mono.failure.native == mock.failure.native)
    require(wall.failure.kind != io.Kind.Ok && wall.failure.kind == mock.failure.kind && wall.failure.native == mock.failure.native)
    after := deadline_after(1)
    require(after.failure.kind != io.Kind.Ok && after.failure.kind == mock.failure.kind && after.failure.native == mock.failure.native && after.value.at.seconds == 0 && after.value.at.nanoseconds == 0)
    expired := deadline_expired(&zero)
    require(expired.failure.kind != io.Kind.Ok && !expired.value && expired.failure.kind == mock.failure.kind && expired.failure.native == mock.failure.native)
    remaining := deadline_remaining(&zero)
    require(remaining.failure.kind != io.Kind.Ok && remaining.value == 0 && remaining.failure.kind == mock.failure.kind && remaining.failure.native == mock.failure.native)
    sleep_mock = SleepResult{ failure: io.Failure{ kind: io.Kind.Interrupted, native: #cast(isize, native) } }
    slept := sleep(1)
    require(slept.failure.kind != io.Kind.Ok && slept.failure.kind == sleep_mock.failure.kind && slept.failure.native == sleep_mock.failure.native)
  }
  require(sleep_calls == 2)
  require(sleep(0).failure.kind == io.Kind.Ok && sleep(-1).failure.kind == io.Kind.Ok && sleep_calls == 2)
  sleep_mock = SleepResult{}
  require(sleep(1).failure.kind == io.Kind.Ok && sleep_calls == 3)
  require(deadline_expired(nil).failure.kind == io.Kind.InvalidInput)
  require(deadline_expired(nil).failure.native == 0)
  require(deadline_remaining(nil).failure.kind == io.Kind.InvalidInput)
  require(deadline_remaining(nil).failure.native == 0)
  max: i64 = 9223372036854775807
  min: i64 = -9223372036854775807 - 1
  add := checked_add(max, 1)
  sub := checked_sub(min, 1)
  require(add.failure.kind == io.Kind.Overflow && add.failure.native == 0)
  require(sub.failure.kind == io.Kind.Overflow && sub.failure.native == 0)
  require(checked_sub(-1, min).value == max)
  require(checked_sub(0, min).failure.kind != io.Kind.Ok)
  require(elapsed(Instant{seconds: min}, Instant{seconds: max}).failure.kind != io.Kind.Ok)
  mock = ClockResult{}
  require(deadline_expired(&zero).failure.kind == io.Kind.Ok && deadline_expired(&zero).value)
  require(deadline_remaining(&zero).failure.kind == io.Kind.Ok && deadline_remaining(&zero).value == 0)
  past := deadline_after(-1)
  require(past.failure.kind == io.Kind.Ok && past.value.at.seconds == -1 && past.value.at.nanoseconds == Second - 1)
  require(deadline_expired(&past.value).value && deadline_remaining(&past.value).value == 0)
  future := deadline_after(Second + 1)
  require(future.failure.kind == io.Kind.Ok && future.value.at.seconds == 1 && future.value.at.nanoseconds == 1)
  require(!deadline_expired(&future.value).value && deadline_remaining(&future.value).value == Second + 1)
  far := Deadline{at: Instant{seconds: max}}
  overflow := deadline_remaining(&far)
  require(overflow.failure.kind != io.Kind.Ok && overflow.failure.kind == io.Kind.Overflow && overflow.failure.native == 0)
  mock = ClockResult{value: Instant{seconds: max, nanoseconds: Second - 1}}
  after := deadline_after(1)
  require(after.failure.kind != io.Kind.Ok && after.failure.kind == io.Kind.Overflow && after.failure.native == 0)
  mock = ClockResult{value: Instant{seconds: min}}
  after = deadline_after(-1)
  require(after.failure.kind != io.Kind.Ok && after.failure.kind == io.Kind.Overflow && after.failure.native == 0)
  mock = ClockResult{value: Instant{seconds: 4, nanoseconds: Second - 1}}
  after = deadline_after(1)
  require(after.failure.kind == io.Kind.Ok && after.value.at.seconds == 5 && after.value.at.nanoseconds == 0)
  mock = ClockResult{value: Instant{seconds: 4}}
  after = deadline_after(-1)
  require(after.failure.kind == io.Kind.Ok && after.value.at.seconds == 3 && after.value.at.nanoseconds == Second - 1)
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
