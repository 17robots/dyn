#!/usr/bin/env python3
"""std/time calendar conversion and std/time/zone against Python datetime and zoneinfo."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import zoneinfo

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
ZONES = ['Europe/Berlin', 'America/New_York', 'Australia/Sydney', 'Asia/Kolkata', 'America/St_Johns',
         'Pacific/Chatham', 'Africa/Casablanca', 'UTC', 'America/Sao_Paulo', 'Europe/London', 'Asia/Tokyo',
         'Antarctica/Troll', 'Pacific/Apia', 'Europe/Dublin', 'America/Santiago']
rng = random.Random(1999)
# 1902 through 2200, past the last transition so footer rules are exercised.
instants = [rng.randrange(-2145916800, 7258118400) for _ in range(400)]
instants += [1711846800 + d for d in (-1, 0, 1, 3599, 3600)] + [1729990800 + d for d in (-1, 0, 1)]
calendar_days = [rng.randrange(-800000, 800000) for _ in range(300)] + [0, -1, 59, 60, -719468, 2932896]
if not Path('/usr/share/zoneinfo/Europe/Berlin').exists():
    print('SKIP time zones: no zoneinfo database')
    raise SystemExit(0)
lines = ['use "std/time" time', 'use "std/time/zone" zone', 'use "std/mem" mem', 'use "std/io" io', '',
         f'const instants: [{len(instants)}]i64 = [{", ".join(map(str, instants))}]',
         f'const days: [{len(calendar_days)}]i64 = [{", ".join(map(str, calendar_days))}]', '',
         'fn main() {', '  arena := mem.arena_create(16777216)', '  defer {', '    mem.arena_release(arena)', '  }',
         '  for day in days {', '    date := time.civil_from_days(day)',
         '    _ = io.println(io.stdout(), "day {} {} {} {} {} {}", day, date.year, date.month, date.day, time.days_from_civil(date.year, date.month, date.day), #cast(u8, time.weekday(&date)))',
         '  }']
for index, name in enumerate(ZONES):
    lines += [f'  loaded{index} := zone.load(arena, "{name}")', f'  if !loaded{index}.ok {{', f'    #panic("load {name}")', '  }',
              '  for seconds in instants {',
              f'    shown := zone.local(&loaded{index}.value, time.Instant{{ seconds: seconds }})',
              f'    back := zone.instant_of_local(&loaded{index}.value, &shown.value)',
              f'    _ = io.println(io.stdout(), "{name} {{}} {{}} {{}} {{}} {{}}-{{}}-{{}} {{}}:{{}}:{{}} {{}}", seconds, shown.offset, shown.dst, shown.abbreviation, shown.value.year, shown.value.month, shown.value.day, shown.value.hour, shown.value.minute, shown.value.second, back.seconds)',
              '  }']
lines += ['  posix := zone.parse_posix(arena, "CET-1CEST,M3.5.0,M10.5.0/3")', '  if !posix.ok {', '    #panic("posix")', '  }',
          '  for seconds in instants {', '    shown := zone.local(&posix.value, time.Instant{ seconds: seconds })',
          '    _ = io.println(io.stdout(), "posix {} {} {}", seconds, shown.offset, shown.abbreviation)', '  }',
          '  bad := zone.parse_posix(arena, "CET-1CEST,M13.5.0")', '  if bad.ok {', '    #panic("bad posix")', '  }',
          '  for seconds in instants {', '    shown := zone.local(&loaded0.value, time.Instant{ seconds: seconds })',
          '    _ = io.println(io.stdout(), "format {} {} {}", seconds, zone.format(arena, "%Y-%m-%d %H:%M:%S %j %a %A %b %B %Z %z %%", &shown), zone.format_rfc3339(arena, &shown))', '  }',
          '  bad_format := zone.local(&loaded0.value, time.Instant{})', '  if #len(zone.format(arena, "%Q", &bad_format)) != 0 {', '    #panic("bad format")', '  }',
          '  system := zone.system(arena)', '  if !system.ok {', '    #panic("system")', '  }',
          '  _ = io.println(io.stdout(), "system {}", system.value.name)', '}']


def expected():
    out = []
    epoch = datetime(1970, 1, 1)
    for day in calendar_days:
        date = (epoch + timedelta(days=day)).date() if -719162 <= day <= 2932896 else None
        if date is None:
            continue
        out.append(f'day {day} {date.year} {date.month} {date.day} {day} {(date.weekday() + 1) % 7}')
    for name in ZONES:
        info = zoneinfo.ZoneInfo(name)
        for seconds in instants:
            moment = datetime.fromtimestamp(seconds, timezone.utc).astimezone(info)
            offset = int(moment.utcoffset().total_seconds())
            dst = 'true' if moment.dst() else 'false'
            # Dyn maps a local time back with the earlier offset; Python fold=0 does the same.
            naive = moment.replace(tzinfo=None)
            back = int(naive.replace(tzinfo=info, fold=0).timestamp())
            out.append(f'{name} {seconds} {offset} {dst} {moment.tzname()} {moment.year}-{moment.month}-{moment.day} '
                       f'{moment.hour}:{moment.minute}:{moment.second} {back}')
    berlin = zoneinfo.ZoneInfo('Europe/Berlin')
    for seconds in instants:
        moment = datetime.fromtimestamp(seconds, timezone.utc).astimezone(berlin)
        if moment.year >= 1997:
            out.append(f'posix {seconds} {int(moment.utcoffset().total_seconds())} {moment.tzname()}')
    for seconds in instants:
        moment = datetime.fromtimestamp(seconds, timezone.utc).astimezone(berlin)
        if 1 <= moment.year <= 9999:
            text = moment.strftime('%Y-%m-%d %H:%M:%S %j %a %A %b %B %Z %z %%')
            out.append(f'format {seconds} {text} {moment.replace(microsecond=0).isoformat()}')
    return out


with tempfile.TemporaryDirectory(prefix='dyn-time-zones-') as directory:
    project = Path(directory)
    (project / 'main.dyn').write_text('\n'.join(lines) + '\n')
    output = project / 'program'
    subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=300)
    got = subprocess.run([str(output)], check=True, capture_output=True, text=True, timeout=60).stdout.splitlines()
    want = expected()
    actual = {line for line in got}
    missing = [line for line in want if line not in actual]
    # Python's datetime has no dates outside years 1-9999; Dyn prints them anyway.
    assert not missing, missing[:8]
    system = [line for line in got if line.startswith('system ')]
    assert system and system[0] != 'system ', got[-1]
    for target in ('aarch64-macos', 'x86_64-windows', 'aarch64-windows'):
        subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--target', target, '--output', str(project / target)], check=True, timeout=300)
    if shutil.which('wine'):
        # Windows has no zoneinfo database: load fails, the system zone works.
        windows = project / 'windows'
        windows.mkdir()
        (windows / 'main.dyn').write_text('''use "std/time/zone" zone
use "std/mem" mem
use "std/errors" errors

fn main() {
  arena := mem.arena_create(1048576)
  defer {
    mem.arena_release(arena)
  }
  if zone.load(arena, "Europe/Berlin").kind != errors.Kind.Unsupported {
    #panic("windows load")
  }
  system := zone.system(arena)
  if !system.ok || #len(system.value.name) == 0 || #len(system.value.standard.abbreviation) == 0 {
    #panic("windows system")
  }
}
''')
        subprocess.run([DYN, 'build', str(windows), '--no-cache', '--quiet', '--target', 'x86_64-windows', '--output', str(windows / 'program.exe')], check=True, timeout=300)
        subprocess.run(['wine', str(windows / 'program.exe')], check=True, capture_output=True, timeout=120)
print(f'PASS time zones: calendar days, {len(ZONES)} zones x {len(instants)} instants against zoneinfo, POSIX rules, strftime and RFC 3339 formatting, system zone (Linux and Windows)')
